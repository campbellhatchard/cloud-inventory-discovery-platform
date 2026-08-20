from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def _property(uno_module, name: str, value):
    prop = uno_module.createUnoStruct("com.sun.star.beans.PropertyValue")
    prop.Name = name
    prop.Value = value
    return prop


def _wait_for_port(port: int, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("LibreOffice UNO listener did not start in time.")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh DOCX TOC/fields using LibreOffice UNO.")
    parser.add_argument("docx")
    parser.add_argument("--pdf")
    parser.add_argument("--libreoffice", default="/usr/bin/libreoffice")
    args = parser.parse_args()

    # Debian installs the pyuno bridge here for the system Python.
    dist_packages = Path("/usr/lib/python3/dist-packages")
    if dist_packages.exists():
        sys.path.append(str(dist_packages))
    try:
        import uno  # type: ignore
    except Exception as exc:
        raise RuntimeError(f"python3-uno is unavailable: {exc}") from exc

    docx_path = Path(args.docx).resolve()
    if not docx_path.exists():
        raise FileNotFoundError(docx_path)
    pdf_path = Path(args.pdf).resolve() if args.pdf else None

    with tempfile.TemporaryDirectory(prefix="ci-discovery-lo-fields-") as profile_dir:
        port = _free_port()
        profile_uri = Path(profile_dir).resolve().as_uri()
        command = [
            args.libreoffice,
            f"-env:UserInstallation={profile_uri}",
            "--headless",
            "--norestore",
            "--nodefault",
            "--nofirststartwizard",
            f"--accept=socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext",
        ]
        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=os.environ.copy(),
        )
        document = None
        try:
            _wait_for_port(port)
            local_context = uno.getComponentContext()
            resolver = local_context.ServiceManager.createInstanceWithContext(
                "com.sun.star.bridge.UnoUrlResolver",
                local_context,
            )
            context = resolver.resolve(
                f"uno:socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext"
            )
            service_manager = context.ServiceManager
            desktop = service_manager.createInstanceWithContext(
                "com.sun.star.frame.Desktop",
                context,
            )
            document = desktop.loadComponentFromURL(
                uno.systemPathToFileUrl(str(docx_path)),
                "_blank",
                0,
                (_property(uno, "Hidden", True),),
            )
            if document is None:
                raise RuntimeError("LibreOffice could not load the generated DOCX.")

            indexes = document.getDocumentIndexes()
            for index in range(indexes.getCount()):
                indexes.getByIndex(index).update()
            try:
                document.getTextFields().refresh()
            except Exception:
                pass

            # Store the refreshed cached TOC result back into the DOCX.
            document.store()

            if pdf_path is not None:
                pdf_path.parent.mkdir(parents=True, exist_ok=True)
                document.storeToURL(
                    uno.systemPathToFileUrl(str(pdf_path)),
                    (_property(uno, "FilterName", "writer_pdf_Export"),),
                )
        finally:
            if document is not None:
                try:
                    document.close(True)
                except Exception:
                    pass
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
