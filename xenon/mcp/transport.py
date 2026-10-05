"""
MCP Transport — JSON-RPC 2.0 传输层。

支持两种传输方式：
- stdio: 通过子进程的标准输入/输出通信
- SSE: 通过 HTTP Server-Sent Events 通信
"""

from __future__ import annotations

import json
import logging
import queue
import subprocess
import threading
import time
from typing import Any


from xenon.utils.llm_client import _create_http_client

logger = logging.getLogger(__name__)


class MCPTransport:
    """MCP 传输基类。"""

    def send(self, message: dict[str, Any]) -> None:
        raise NotImplementedError

    def receive(self) -> dict[str, Any]:
        raise NotImplementedError

    def close(self) -> None:
        pass


class StdioTransport(MCPTransport):
    """通过子进程 stdio 通信。"""

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.command = command
        self.args = args or []
        self.env = env
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._request_id = 0
        # stdout 行缓冲：跨多次 _readline_with_timeout 调用保留未消费字节，
        # 避免与 BufferedReader 内部缓冲冲突。
        self._read_buf = bytearray()
        self._stdout_chunks: queue.Queue = queue.Queue(maxsize=64)
        self._stderr_tail = bytearray()
        self._stderr_lock = threading.Lock()
        self._stop_readers = threading.Event()
        self._readers: list[threading.Thread] = []
        self._stdout_eof = False
        self._start()

    def _start(self) -> None:
        """启动子进程。"""
        cmd = [self.command] + self.args
        import os

        # ``echo`` is a cmd.exe builtin on Windows, so CreateProcess cannot
        # resolve it as a standalone executable.  Preserve compatibility with
        # legacy MCP registrations by launching the builtin through cmd; real
        # MCP servers should continue to use an executable command.
        if os.name == "nt" and self.command.lower() in {"echo", "type", "ver"}:
            cmd = ["cmd.exe", "/d", "/s", "/c", self.command, *self.args]

        child_env = dict(os.environ)
        child_env["PYTHONIOENCODING"] = "utf-8"
        if self.env:
            child_env.update(self.env)

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=child_env,
                text=False,
            )
            self._readers = [
                threading.Thread(
                    target=self._pump_stdout,
                    args=(self._proc.stdout, self._stdout_chunks, self._stop_readers),
                    daemon=True,
                    name="xenon-mcp-stdout",
                ),
                threading.Thread(
                    target=self._pump_stderr,
                    args=(self._proc.stderr, self._stderr_tail, self._stderr_lock),
                    daemon=True,
                    name="xenon-mcp-stderr",
                ),
            ]
            for reader in self._readers:
                reader.start()
            logger.info(f"MCP 子进程启动: {' '.join(cmd)} (PID: {self._proc.pid})")
        except FileNotFoundError:
            raise RuntimeError(f"MCP 命令不存在: {self.command}")
        except Exception as e:
            raise RuntimeError(f"MCP 子进程启动失败: {e}")

    def send(self, message: dict[str, Any]) -> None:
        """发送 JSON-RPC 消息。"""
        if not self._proc or self._proc.poll() is not None:
            raise RuntimeError("MCP 子进程未运行")

        data = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        with self._lock:
            try:
                self._proc.stdin.write(data)
                self._proc.stdin.flush()
            except Exception as e:
                raise RuntimeError(f"MCP 发送失败: {e}")

    def receive(self, timeout: float = 30.0) -> dict[str, Any]:
        """接收 JSON-RPC 消息（带墙钟超时，避免 readline 无限阻塞）。"""
        if not self._proc:
            raise RuntimeError("MCP 子进程未运行")

        with self._lock:
            deadline = time.monotonic() + timeout
            line = self._readline_with_timeout(deadline)
            if line is None:
                raise RuntimeError(f"MCP 接收超时：{timeout}s 内无输出")
            if line == "":
                stderr = self._read_stderr_safely()
                raise RuntimeError(f"MCP 子进程无输出（EOF）。stderr: {stderr[:500]}")
            try:
                return json.loads(line)
            except json.JSONDecodeError as e:
                raise RuntimeError(f"MCP 响应解析失败: {e}")

    def _readline_with_timeout(self, deadline: float) -> str | None:
        """从 stdout 读取一行，带整体 deadline 墙钟超时。

        后台线程读取管道，队列等待使用整体 deadline。Windows 的 select
        仅支持 socket，不能用于子进程管道。返回值约定：
          - 行字符串（含 ``\\n``，已 utf-8 解码）：读到完整一行；
          - ``""``：遇到 EOF 且缓冲区无残留；
          - ``None``：deadline 超时，未读到完整行。
        """
        while True:
            nl = self._read_buf.find(b"\n")
            if nl >= 0:
                line = bytes(self._read_buf[: nl + 1])
                del self._read_buf[: nl + 1]
                return line.decode("utf-8", errors="replace")
            if self._stdout_eof:
                line = bytes(self._read_buf)
                self._read_buf.clear()
                return line.decode("utf-8", errors="replace")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                chunk = self._stdout_chunks.get(timeout=remaining)
            except queue.Empty:
                return None
            if not chunk:
                self._stdout_eof = True
            else:
                self._read_buf += chunk

    @staticmethod
    def _pump_stdout(stream, chunks, stop) -> None:
        """Drain stdout with bounded buffering and a cancellable queue writer."""
        try:
            while not stop.is_set():
                chunk = stream.read1(8192)
                while not stop.is_set():
                    try:
                        chunks.put(chunk, timeout=0.1)
                        break
                    except queue.Full:
                        continue
                if not chunk:
                    return
        except (OSError, ValueError):
            if not stop.is_set():
                try:
                    chunks.put(b"", timeout=0.1)
                except queue.Full:
                    pass

    @staticmethod
    def _pump_stderr(stream, tail, lock) -> None:
        """Continuously drain diagnostics so a full stderr pipe cannot deadlock."""
        try:
            while chunk := stream.read1(4096):
                with lock:
                    tail.extend(chunk)
                    del tail[:-8192]
        except (OSError, ValueError):
            pass

    def _read_stderr_safely(self) -> str:
        """非阻塞读取 stderr 当前可读内容（仅用于错误诊断）。"""
        with self._stderr_lock:
            return bytes(self._stderr_tail).decode("utf-8", errors="replace")

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        max_lines: int = 50,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """发送请求并等待响应（原子操作，带墙钟超时）。

        - ``max_lines``：最多读取的行数上限（防止被无关通知/日志行无限消耗）。
        - ``timeout``：整体墙钟超时（秒）；超时抛 ``RuntimeError``。
          （B11：替代原先 ``max_retries`` 仅限行数、单行 readline 仍可无限阻塞的缺陷。）
        """
        with self._lock:
            if not self._proc or self._proc.poll() is not None:
                raise RuntimeError("MCP 子进程未运行")

            self._request_id += 1
            request_id = self._request_id
            message = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
            }
            if params:
                message["params"] = params

            data = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
            try:
                self._proc.stdin.write(data)
                self._proc.stdin.flush()
            except Exception as e:
                raise RuntimeError(f"MCP 发送失败: {e}")

            # 等待响应（匹配 id），带墙钟 deadline 与行数上限
            deadline = time.monotonic() + timeout
            for _ in range(max_lines):
                line = self._readline_with_timeout(deadline)
                if line is None:
                    raise RuntimeError(
                        f"MCP 请求超时：{timeout}s 内未收到 id={request_id} 的响应"
                    )
                if line == "":
                    stderr = self._read_stderr_safely()
                    raise RuntimeError(
                        f"MCP 子进程无输出（EOF）。stderr: {stderr[:500]}"
                    )
                try:
                    response = json.loads(line)
                except json.JSONDecodeError as e:
                    raise RuntimeError(f"MCP 响应解析失败: {e}")

                if response.get("id") == request_id:
                    return response
                if "id" not in response:
                    logger.debug(f"MCP 通知: {response.get('method', 'unknown')}")
                    continue

            raise RuntimeError(
                f"MCP 请求超时：读取 {max_lines} 行后仍未收到 id={request_id} 的响应"
            )

    def close(self) -> None:
        """关闭子进程。"""
        if self._proc:
            self._stop_readers.set()
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                    self._proc.wait(timeout=5)
                except Exception:
                    pass
            for reader in self._readers:
                reader.join(timeout=1)
            for stream in (self._proc.stdin, self._proc.stdout, self._proc.stderr):
                try:
                    stream.close()
                except (OSError, ValueError):
                    pass
            self._proc = None

    def __del__(self) -> None:
        self.close()


class SSETransport(MCPTransport):
    """通过 HTTP SSE 通信。"""

    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        *,
        timeout: float = 30.0,
    ) -> None:
        self.url = url
        self.headers = headers or {}
        self._client = _create_http_client(timeout=timeout)
        self._request_id = 0

    def send(self, message: dict[str, Any]) -> None:
        """通过 HTTP POST 发送消息。"""
        try:
            resp = self._client.post(
                self.url,
                json=message,
                headers={**self.headers, "Content-Type": "application/json"},
            )
            resp.raise_for_status()
        except Exception as e:
            raise RuntimeError(f"MCP SSE 发送失败: {e}")

    def receive(self) -> dict[str, Any]:
        """通过 SSE 接收消息。"""
        try:
            with self._client.stream("GET", self.url, headers=self.headers) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if line.startswith("data:"):
                        data = line[5:].strip()
                        if data:
                            return json.loads(data)
            raise RuntimeError("SSE 连接关闭")
        except Exception as e:
            raise RuntimeError(f"MCP SSE 接收失败: {e}")

    def request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """发送请求。SSE 模式下直接用 POST 请求-响应。"""
        self._request_id += 1
        message = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
        }
        if params:
            message["params"] = params

        try:
            resp = self._client.post(
                self.url,
                json=message,
                headers={**self.headers, "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            raise RuntimeError(f"MCP SSE 请求失败: {e}")

    def close(self) -> None:
        self._client.close()
