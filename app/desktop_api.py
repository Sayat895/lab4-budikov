import base64
import binascii
from pathlib import Path

import webview


class DesktopApi:
    def __init__(self):
        self._window = None

    def save_report(self, filename: str, content_base64: str) -> dict:
        filename = Path(filename).name
        if not filename.lower().endswith(".xlsx"):
            filename = f"{filename}.xlsx"
        try:
            content = base64.b64decode(content_base64, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("Не удалось прочитать файл отчета.") from error
        if not content.startswith(b"PK"):
            raise ValueError("Содержимое файла не является книгой Excel.")
        if self._window is None:
            raise RuntimeError("Окно приложения еще не готово.")

        selected = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename=filename,
            file_types=("Книга Excel (*.xlsx)",),
        )
        if not selected:
            return {"cancelled": True}

        selected_path = selected if isinstance(selected, str) else selected[0]
        path = Path(selected_path)
        if path.suffix.lower() != ".xlsx":
            path = path.with_suffix(".xlsx")
        path.write_bytes(content)
        return {"cancelled": False, "path": str(path)}
