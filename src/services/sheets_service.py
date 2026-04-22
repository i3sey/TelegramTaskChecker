"""Google Sheets integration service for review results."""
import os
from datetime import datetime
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.utils.logging import logger


class SheetsService:
    """Service for sending review results to Google Sheets."""

    # Spreadsheet column mapping
    COLUMNS = {
        "submission_id": "A",
        "timestamp": "B",
        "campaign": "C",
        "author": "D",
        "group": "E",
        "reviewer": "F",
        "score": "G",
        "comment": "H",
    }

    def __init__(self, spreadsheet_id: str, credentials_path: str):
        """
        Initialize Sheets service.

        Args:
            spreadsheet_id: Google Sheets spreadsheet ID
            credentials_path: Path to service account credentials JSON file
        """
        self.spreadsheet_id = spreadsheet_id
        self.credentials_path = os.path.expanduser(credentials_path)
        self._service = None

    async def _get_service(self):
        """Get or create Google Sheets API service."""
        if self._service is None:
            try:
                credentials = service_account.Credentials.from_service_account_file(
                    self.credentials_path,
                    scopes=["https://www.googleapis.com/auth/spreadsheets"],
                )
                self._service = build("sheets", "v4", credentials=credentials)
            except FileNotFoundError:
                logger.error(f"Credentials file not found: {self.credentials_path}")
                raise
            except Exception as e:
                logger.error(f"Failed to create Google Sheets service: {e}")
                raise
        return self._service

    async def _get_next_row(self) -> int:
        """Find the next empty row in the spreadsheet."""
        service = await self._get_service()
        try:
            result = service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range="A:A",
            ).execute()
            values = result.get("values", [])
            return len(values) + 1
        except Exception as e:
            logger.error(f"Failed to get row count: {e}")
            return 2  # Default to row 2 if can't determine

    async def _format_value(self, value: Any) -> str:
        """Format value for spreadsheet."""
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.strftime("%d.%m.%Y %H:%M")
        return str(value)

    async def append_review(self, review_data: dict) -> None:
        """
        Append a new review row to the spreadsheet.

        Args:
            review_data: Dictionary with keys:
                - submission_id: Submission ID
                - timestamp: datetime of review
                - campaign: Campaign title
                - author: Author's full name
                - group: Author's study group
                - reviewer: Reviewer's full name
                - score: Review score
                - comment: Review comment (optional)
        """
        service = await self._get_service()

        # Prepare row values
        row_values = [
            self._format_value(review_data.get("submission_id", "")),
            self._format_value(review_data.get("timestamp", datetime.now())),
            self._format_value(review_data.get("campaign", "")),
            self._format_value(review_data.get("author", "")),
            self._format_value(review_data.get("group", "")),
            self._format_value(review_data.get("reviewer", "")),
            self._format_value(review_data.get("score", "")),
            self._format_value(review_data.get("comment", "")),
        ]

        # Get next row number
        next_row = await self._get_next_row()
        range_name = f"A{next_row}:H{next_row}"

        body = {
            "values": [row_values],
        }

        try:
            result = service.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range=range_name,
                valueInputOption="USER_ENTERED",
                body=body,
            ).execute()
            logger.info(
                f"Appended review to spreadsheet: "
                f"updated {result.get('updatedCells', 0)} cells, "
                f"submission_id={review_data.get('submission_id')}"
            )
        except HttpError as e:
            logger.error(f"Failed to append to spreadsheet: {e}")
            raise

    async def update_review(self, row: int, review_data: dict) -> None:
        """
        Update an existing row in the spreadsheet.

        Args:
            row: Row number to update (1-based, including header)
            review_data: Dictionary with updated values
        """
        service = await self._get_service()

        # Prepare row values
        row_values = [
            self._format_value(review_data.get("submission_id", "")),
            self._format_value(review_data.get("timestamp", "")),
            self._format_value(review_data.get("campaign", "")),
            self._format_value(review_data.get("author", "")),
            self._format_value(review_data.get("group", "")),
            self._format_value(review_data.get("reviewer", "")),
            self._format_value(review_data.get("score", "")),
            self._format_value(review_data.get("comment", "")),
        ]

        range_name = f"A{row}:H{row}"
        body = {
            "values": [row_values],
        }

        try:
            result = service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=range_name,
                valueInputOption="USER_ENTERED",
                body=body,
            ).execute()
            logger.info(
                f"Updated spreadsheet row {row}: "
                f"updated {result.get('updatedCells', 0)} cells"
            )
        except HttpError as e:
            logger.error(f"Failed to update spreadsheet: {e}")
            raise

    async def get_spreadsheet_id(self) -> str:
        """
        Get the spreadsheet ID.

        Returns:
            Spreadsheet ID string
        """
        return self.spreadsheet_id