"""Log rendering helpers for execute mode."""


class ExecuteLoggingMixin:
    def log_print(self, text):
        """Append one colored log line to the console panel."""
        if "成功" in text:
            color = "#4CAF50"
        elif "失败" in text or "错误" in text:
            color = "#F44336"
        elif "===" in text:
            color = "#2196F3"
        else:
            color = "#D4D4D4"

        self.log_output.append(f'<span style="color:{color};">{text}</span>')
        self.log_output.verticalScrollBar().setValue(
            self.log_output.verticalScrollBar().maximum()
        )
