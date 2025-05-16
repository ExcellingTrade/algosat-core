"""
rich_utils.py

This module provides a `ProgressHandler` class for managing and displaying
progress bars and messages using the Rich library.

The `ProgressHandler` is implemented as a singleton to ensure that a single
instance of the progress bar is used throughout the application.

Features:
- Provides a global `Progress` object for consistent progress handling.
- Supports console-based progress bars with a transient display.
- Easy access to the `Progress` object from anywhere in the code.

Usage:
    from common.rich_utils import progress_handler

    With progress_handler.progress:
        task = progress_handler.progress.add_task("Processing...", total=100)
        progress_handler.progress.update(task, advance=10)

Dependencies:
- `rich.progress.Progress`
- `rich.console.Console`
"""
from rich.progress import BarColumn, Progress, Console, TextColumn, TimeRemainingColumn


class ProgressHandler:
    """
        Singleton class to manage and provide a global Rich Progress object.

        This class ensures consistent handling of progress bars and messages
        across the application.
    """
    _instance = None

    def __init__(self, **progress_kwargs):
        if not ProgressHandler._instance:
            self.console = Console(width=150)
            self.progress = Progress(
                TextColumn("[bold blue]{task.description}[/]"),
                BarColumn(),
                "[progress.percentage]{task.percentage:>3.1f}%",
                TimeRemainingColumn(),
                transient=True,  # Progress bar disappears after completion
                expand=True,
                console=self.console,
                **progress_kwargs
            )
            ProgressHandler._instance = self

    @staticmethod
    def get_instance():
        """
        Retrieve the singleton instance of ProgressHandler.

        This method ensures that only one instance of the ProgressHandler
        class exists throughout the application. If an instance doesn't
        exist, it creates one.

        :return: The singleton instance of ProgressHandler.
        """
        if not ProgressHandler._instance:
            ProgressHandler()
        return ProgressHandler._instance

    def print_message(self, message: str, color: str = "green"):
        """
        Print a message to the console used by the progress bar.

        :param message: The message to print.
        :param color: The color for displaying the message.
        """
        self.console.print(f"[{color}]{message}[/]")

    def stop_progress(self):
        """
        Stop and clean up the progress bar.

        This method ensures that any active progress tasks are stopped
        and the console is returned to its default state.
        """
        self.progress.stop()


# Access the global progress handler anywhere
progress_handler = ProgressHandler.get_instance()