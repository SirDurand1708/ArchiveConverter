import ctypes
import json
import sys
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional


DEFAULT_MUTEX_NAME = r"Local\ArchiveConverterSingleInstanceMutex"
DEFAULT_PIPE_NAME = r"\\.\pipe\ArchiveConverterIPC"

_ERROR_ALREADY_EXISTS = 183
_PIPE_ACCESS_INBOUND = 0x00000001
_PIPE_TYPE_BYTE = 0x00000000
_PIPE_READMODE_BYTE = 0x00000000
_PIPE_WAIT = 0x00000000
_PIPE_UNLIMITED_INSTANCES = 255
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_GENERIC_WRITE = 0x40000000
_OPEN_EXISTING = 3


class SingleInstanceManager:
    """
    Garantiza instancia única en Windows mediante Named Mutex + Named Pipe IPC
    con PIPE_UNLIMITED_INSTANCES y backoff en clientes para ráfagas de menú contextual.
    """

    _active_instance: Optional["SingleInstanceManager"] = None
    _active_lock = threading.Lock()

    def __init__(
        self,
        mutex_name: str = DEFAULT_MUTEX_NAME,
        pipe_name: str = DEFAULT_PIPE_NAME,
    ):
        self.mutex_name = mutex_name
        self.pipe_name = pipe_name
        self._mutex_handle: Optional[int] = None
        self._stop_event = threading.Event()
        self._server_thread: Optional[threading.Thread] = None
        self._on_files_received: Optional[Callable[[List[str]], None]] = None

    @classmethod
    def release_active(cls) -> None:
        with cls._active_lock:
            inst = cls._active_instance
            cls._active_instance = None
        if inst is not None:
            inst.release()

    def acquire_or_forward(
        self,
        args: List[str],
        on_files_received: Optional[Callable[[List[str]], None]] = None,
        forward_timeout: float = 10.0,
    ) -> bool:
        """
        Intenta adquirir el Mutex primario.
        - Si es primaria: arranca el servidor Named Pipe y devuelve True.
        - Si ya existe otra instancia: reenvía `args` por Named Pipe y devuelve False.
        """
        if sys.platform != "win32":
            return True

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        handle = kernel32.CreateMutexW(None, True, self.mutex_name)
        last_err = kernel32.GetLastError()

        if not handle:
            return True

        if last_err == _ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
            self.send_args_to_primary(args, pipe_name=self.pipe_name, timeout=forward_timeout)
            return False

        self._mutex_handle = int(handle)
        self._on_files_received = on_files_received
        self._stop_event.clear()
        self._server_thread = threading.Thread(
            target=self._pipe_server_loop,
            daemon=True,
            name="ArchiveConverter-IPC-Server",
        )
        self._server_thread.start()

        with self._active_lock:
            SingleInstanceManager._active_instance = self
        return True

    @staticmethod
    def send_args_to_primary(
        args: List[str],
        pipe_name: str = DEFAULT_PIPE_NAME,
        timeout: float = 10.0,
    ) -> bool:
        """Envía rutas de archivo a la instancia primaria con WaitNamedPipe + backoff."""
        if sys.platform != "win32":
            return False

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateFileW.restype = ctypes.c_void_p
        payload = json.dumps({"files": [str(a) for a in args], "activate": True}, ensure_ascii=False).encode("utf-8")

        deadline = time.monotonic() + timeout
        delay = 0.05
        while time.monotonic() < deadline:
            h_pipe = kernel32.CreateFileW(
                pipe_name,
                _GENERIC_WRITE,
                0,
                None,
                _OPEN_EXISTING,
                0,
                None,
            )
            if h_pipe and h_pipe != _INVALID_HANDLE_VALUE:
                try:
                    written = ctypes.c_uint32(0)
                    ok = kernel32.WriteFile(
                        ctypes.c_void_p(h_pipe),
                        payload,
                        len(payload),
                        ctypes.byref(written),
                        None,
                    )
                    kernel32.FlushFileBuffers(ctypes.c_void_p(h_pipe))
                    return bool(ok)
                finally:
                    kernel32.CloseHandle(ctypes.c_void_p(h_pipe))

            kernel32.WaitNamedPipeW(pipe_name, int(min(250, max(50, (deadline - time.monotonic()) * 1000))))
            time.sleep(delay)
            delay = min(0.25, delay * 1.5)
        return False

    def _pipe_server_loop(self) -> None:
        if sys.platform != "win32":
            return
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateNamedPipeW.restype = ctypes.c_void_p

        while not self._stop_event.is_set():
            h_pipe = kernel32.CreateNamedPipeW(
                self.pipe_name,
                _PIPE_ACCESS_INBOUND,
                _PIPE_TYPE_BYTE | _PIPE_READMODE_BYTE | _PIPE_WAIT,
                _PIPE_UNLIMITED_INSTANCES,
                4096,
                4096,
                0,
                None,
            )
            if not h_pipe or h_pipe == _INVALID_HANDLE_VALUE:
                time.sleep(0.1)
                continue

            try:
                connected = kernel32.ConnectNamedPipe(ctypes.c_void_p(h_pipe), None)
                if not connected and kernel32.GetLastError() != 535:  # ERROR_PIPE_CONNECTED
                    continue
                if self._stop_event.is_set():
                    break

                chunks: List[bytes] = []
                buf = ctypes.create_string_buffer(4096)
                bytes_read = ctypes.c_uint32(0)
                while True:
                    ok = kernel32.ReadFile(
                        ctypes.c_void_p(h_pipe),
                        buf,
                        4096,
                        ctypes.byref(bytes_read),
                        None,
                    )
                    if not ok or bytes_read.value == 0:
                        break
                    chunks.append(buf.raw[: bytes_read.value])

                raw = b"".join(chunks).decode("utf-8", errors="replace").strip()
                if raw:
                    try:
                        msg = json.loads(raw)
                        files = msg.get("files") or []
                        if callable(self._on_files_received):
                            self._on_files_received([str(f) for f in files if f])
                    except Exception:
                        pass
            finally:
                kernel32.DisconnectNamedPipe(ctypes.c_void_p(h_pipe))
                kernel32.CloseHandle(ctypes.c_void_p(h_pipe))

    def release(self) -> None:
        self._stop_event.set()
        if sys.platform == "win32":
            # Desbloquear ConnectNamedPipe si está esperando cliente
            try:
                self.send_args_to_primary([], pipe_name=self.pipe_name, timeout=0.3)
            except Exception:
                pass

            if self._mutex_handle:
                kernel32 = ctypes.windll.kernel32
                try:
                    kernel32.ReleaseMutex(ctypes.c_void_p(self._mutex_handle))
                except Exception:
                    pass
                try:
                    kernel32.CloseHandle(ctypes.c_void_p(self._mutex_handle))
                except Exception:
                    pass
                self._mutex_handle = None
