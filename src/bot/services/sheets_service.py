"""Google Sheets integration service for review results."""
import os
import re
from datetime import datetime
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.bot.utils.logging import logger

class SheetsService:
    """Service for sending review results to Google Sheets."""

    REVIEW_HEADERS = [
        "submission_id",
        "timestamp",
        "campaign",
        "author",
        "group",
        "reviewer",
        "score",
        "comment",
    ]

    REVIEW_SHEET_NAME = "Reviews"
    SHEETS_SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    def __init__(
        self,
        spreadsheet_id: str | None,
        credentials_path: str,
    ):
        """
        Initialize Sheets service.

        Args:
            spreadsheet_id: Google Sheets spreadsheet ID for legacy direct writes.
                Can be None for dynamic export into a newly created spreadsheet.
            credentials_path: Path to service account credentials JSON file
        """
        self.spreadsheet_id = spreadsheet_id
        self.credentials_path = os.path.expanduser(credentials_path)
        self._sheets_service = None
        self._drive_service = None

    async def _get_credentials(self):
        """Load service account credentials."""
        try:
            return service_account.Credentials.from_service_account_file(
                self.credentials_path,
                scopes=self.SHEETS_SCOPES,
            )
        except FileNotFoundError:
            logger.error(f"Credentials file not found: {self.credentials_path}")
            raise
        except Exception as e:
            logger.error(f"Failed to load Google credentials: {e}")
            raise

    async def _get_sheets_service(self):
        """Get or create Google Sheets API service."""
        if self._sheets_service is None:
            credentials = await self._get_credentials()
            try:
                self._sheets_service = build("sheets", "v4", credentials=credentials)
            except Exception as e:
                logger.error(f"Failed to create Google Sheets service: {e}")
                raise
        return self._sheets_service

    async def _get_drive_service(self):
        """Get or create Google Drive API service."""
        if self._drive_service is None:
            credentials = await self._get_credentials()
            try:
                self._drive_service = build("drive", "v3", credentials=credentials)
            except Exception as e:
                logger.error(f"Failed to create Google Drive service: {e}")
                raise
        return self._drive_service

    @staticmethod
    def _format_value(value: Any) -> str:
        """Format value for spreadsheet."""
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.strftime("%d.%m.%Y %H:%M")
        return str(value)

    @staticmethod
    def _quote_sheet_name(sheet_name: str) -> str:
        """Quote sheet name for A1 notation."""
        escaped = sheet_name.replace("'", "''")
        return f"'{escaped}'"

    @staticmethod
    def _column_letter(index: int) -> str:
        """Convert 1-based column index to spreadsheet column letter."""
        result = ""
        while index > 0:
            index, remainder = divmod(index - 1, 26)
            result = chr(65 + remainder) + result
        return result

    @staticmethod
    def _sheet_title_for_campaign(campaign_id: int, campaign_title: str) -> str:
        """Build a safe sheet title for campaign export."""
        sanitized_title = re.sub(r"[\[\]\*:/\\\?]", "_", campaign_title).strip()
        base_title = f"Campaign {campaign_id}"
        if sanitized_title:
            base_title = f"{base_title} - {sanitized_title}"
        return base_title[:100]

    @staticmethod
    def _spreadsheet_title_for_campaign(campaign_id: int, campaign_title: str) -> str:
        """Build spreadsheet title for campaign export."""
        sanitized_title = re.sub(r"\s+", " ", campaign_title).strip()
        base_title = f"Campaign Export {campaign_id}"
        if sanitized_title:
            base_title = f"{base_title} - {sanitized_title}"
        return base_title[:120]

    def _require_spreadsheet_id(self) -> str:
        """Return configured spreadsheet ID or raise."""
        if not self.spreadsheet_id:
            raise ValueError("Spreadsheet ID is not configured")
        return self.spreadsheet_id

    async def _get_sheet_metadata(self, spreadsheet_id: str | None = None) -> dict[str, Any]:
        """Fetch spreadsheet metadata."""
        service = await self._get_sheets_service()
        target_spreadsheet_id = spreadsheet_id or self._require_spreadsheet_id()
        return service.spreadsheets().get(
            spreadsheetId=target_spreadsheet_id
        ).execute()

    async def ensure_sheet_exists(
        self,
        sheet_name: str,
        spreadsheet_id: str | None = None,
    ) -> None:
        """Create a sheet if it does not exist yet."""
        target_spreadsheet_id = spreadsheet_id or self._require_spreadsheet_id()
        metadata = await self._get_sheet_metadata(target_spreadsheet_id)
        sheets = metadata.get("sheets", [])
        for sheet in sheets:
            properties = sheet.get("properties", {})
            if properties.get("title") == sheet_name:
                return

        service = await self._get_sheets_service()
        try:
            service.spreadsheets().batchUpdate(
                spreadsheetId=target_spreadsheet_id,
                body={
                    "requests": [
                        {
                            "addSheet": {
                                "properties": {
                                    "title": sheet_name,
                                }
                            }
                        }
                    ]
                },
            ).execute()
            logger.info(
                f"Created sheet '{sheet_name}' in spreadsheet {target_spreadsheet_id}"
            )
        except HttpError as e:
            logger.error(f"Failed to create sheet '{sheet_name}': {e}")
            raise

    async def clear_sheet(
        self,
        sheet_name: str,
        spreadsheet_id: str | None = None,
    ) -> None:
        """Clear all values from a sheet."""
        service = await self._get_sheets_service()
        target_spreadsheet_id = spreadsheet_id or self._require_spreadsheet_id()
        quoted_sheet_name = self._quote_sheet_name(sheet_name)
        try:
            service.spreadsheets().values().clear(
                spreadsheetId=target_spreadsheet_id,
                range=quoted_sheet_name,
                body={},
            ).execute()
            logger.info(
                f"Cleared sheet '{sheet_name}' in spreadsheet {target_spreadsheet_id}"
            )
        except HttpError as e:
            logger.error(f"Failed to clear sheet '{sheet_name}': {e}")
            raise

    async def write_rows(
        self,
        sheet_name: str,
        rows: list[list[Any]],
        header: list[str] | None = None,
        spreadsheet_id: str | None = None,
    ) -> int:
        """
        Rewrite sheet contents with header and rows.

        Args:
            sheet_name: Target sheet name
            rows: Data rows
            header: Optional header row
            spreadsheet_id: Optional target spreadsheet ID

        Returns:
            Number of data rows written (without header)
        """
        target_spreadsheet_id = spreadsheet_id or self._require_spreadsheet_id()
        await self.ensure_sheet_exists(
            sheet_name=sheet_name,
            spreadsheet_id=target_spreadsheet_id,
        )

        values: list[list[str]] = []
        if header:
            values.append([self._format_value(value) for value in header])
        values.extend(
            [[self._format_value(value) for value in row] for row in rows]
        )

        await self.clear_sheet(
            sheet_name=sheet_name,
            spreadsheet_id=target_spreadsheet_id,
        )

        if not values:
            return 0

        last_column = self._column_letter(len(values[0]))
        range_name = f"{self._quote_sheet_name(sheet_name)}!A1:{last_column}{len(values)}"
        body = {"values": values}

        service = await self._get_sheets_service()
        try:
            result = service.spreadsheets().values().update(
                spreadsheetId=target_spreadsheet_id,
                range=range_name,
                valueInputOption="USER_ENTERED",
                body=body,
            ).execute()
            logger.info(
                f"Wrote {len(rows)} rows to sheet '{sheet_name}' in spreadsheet "
                f"{target_spreadsheet_id}: updated {result.get('updatedCells', 0)} cells"
            )
            return len(rows)
        except HttpError as e:
            logger.error(f"Failed to write rows to sheet '{sheet_name}': {e}")
            raise

    async def create_spreadsheet(
        self,
        title: str,
        sheet_name: str,
    ) -> str:
        """
        Create a new spreadsheet for export in the service account root Drive.

        Args:
            title: Spreadsheet title
            sheet_name: Initial sheet name

        Returns:
            Created spreadsheet ID
        """
        drive_service = await self._get_drive_service()
        try:
            result = drive_service.files().create(
                body={
                    "name": title,
                    "mimeType": "application/vnd.google-apps.spreadsheet",
                },
                fields="id",
            ).execute()
            spreadsheet_id = result["id"]
            await self._rename_initial_sheet(
                spreadsheet_id=spreadsheet_id,
                sheet_name=sheet_name,
            )
            logger.info(
                f"Created spreadsheet '{title}' in service account root with id={spreadsheet_id}"
            )
            return spreadsheet_id
        except HttpError as e:
            logger.error(f"Failed to create spreadsheet '{title}' in service account root: {e}")
            raise

    async def _rename_initial_sheet(self, spreadsheet_id: str, sheet_name: str) -> None:
        """Rename the default initial sheet in a newly created spreadsheet."""
        metadata = await self._get_sheet_metadata(spreadsheet_id)
        sheets = metadata.get("sheets", [])
        if not sheets:
            raise ValueError(f"Spreadsheet {spreadsheet_id} does not contain any sheets")

        first_sheet = sheets[0]
        properties = first_sheet.get("properties", {})
        current_title = properties.get("title")
        sheet_id = properties.get("sheetId")

        if current_title == sheet_name:
            return
        if sheet_id is None:
            raise ValueError(f"Unable to determine initial sheet id for spreadsheet {spreadsheet_id}")

        service = await self._get_sheets_service()
        try:
            service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "requests": [
                        {
                            "updateSheetProperties": {
                                "properties": {
                                    "sheetId": sheet_id,
                                    "title": sheet_name,
                                },
                                "fields": "title",
                            }
                        }
                    ]
                },
            ).execute()
            logger.info(
                f"Renamed initial sheet in spreadsheet {spreadsheet_id} from '{current_title}' to '{sheet_name}'"
            )
        except HttpError as e:
            logger.error(
                f"Failed to rename initial sheet in spreadsheet {spreadsheet_id} to '{sheet_name}': {e}"
            )
            raise

    async def delete_file(self, file_id: str) -> None:
        """Delete a Google Drive file, ignoring missing file errors."""
        drive_service = await self._get_drive_service()
        try:
            drive_service.files().delete(fileId=file_id).execute()
            logger.info(f"Deleted previous Google Drive file {file_id}")
        except HttpError as e:
            status_code = getattr(getattr(e, "resp", None), "status", None)
            if status_code == 404:
                logger.warning(
                    f"Previous Google Drive file {file_id} was not found during deletion"
                )
                return
            logger.error(f"Failed to delete Google Drive file {file_id}: {e}")
            raise

    async def make_spreadsheet_public(self, spreadsheet_id: str) -> None:
        """
        Grant link-based public read access to spreadsheet.

        Args:
            spreadsheet_id: Spreadsheet ID
        """
        drive_service = await self._get_drive_service()
        try:
            drive_service.permissions().create(
                fileId=spreadsheet_id,
                body={
                    "type": "anyone",
                    "role": "reader",
                },
                fields="id",
            ).execute()
            logger.info(f"Made spreadsheet {spreadsheet_id} publicly accessible by link")
        except HttpError as e:
            logger.error(f"Failed to make spreadsheet {spreadsheet_id} public: {e}")
            raise

    @staticmethod
    def build_force_copy_url(spreadsheet_id: str) -> str:
        """Build a Google Sheets force-copy URL."""
        return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/copy"

    async def export_campaign_rows(
        self,
        campaign_id: int,
        campaign_title: str,
        rows: list[list[Any]],
        header: list[str],
        previous_spreadsheet_id: str | None = None,
    ) -> tuple[str, str, int, str]:
        """
        Export completed campaign rows into a dedicated spreadsheet.

        Args:
            campaign_id: Campaign ID
            campaign_title: Campaign title
            rows: Export data rows
            header: Header row
            previous_spreadsheet_id: Existing spreadsheet ID to delete before export

        Returns:
            Tuple of (spreadsheet_id, sheet_name, written_rows_count, force_copy_url)
        """
        if previous_spreadsheet_id:
            await self.delete_file(previous_spreadsheet_id)

        sheet_name = self._sheet_title_for_campaign(campaign_id, campaign_title)
        spreadsheet_title = self._spreadsheet_title_for_campaign(campaign_id, campaign_title)
        spreadsheet_id = await self.create_spreadsheet(
            title=spreadsheet_title,
            sheet_name=sheet_name,
        )
        written_rows = await self.write_rows(
            sheet_name=sheet_name,
            rows=rows,
            header=header,
            spreadsheet_id=spreadsheet_id,
        )
        await self.make_spreadsheet_public(spreadsheet_id)
        return (
            spreadsheet_id,
            sheet_name,
            written_rows,
            self.build_force_copy_url(spreadsheet_id),
        )

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
        service = await self._get_sheets_service()
        spreadsheet_id = self._require_spreadsheet_id()

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

        range_name = f"{self._quote_sheet_name(self.REVIEW_SHEET_NAME)}!A:H"
        body = {
            "values": [row_values],
        }

        try:
            result = service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body=body,
            ).execute()
            logger.info(
                f"Appended review to spreadsheet: "
                f"updated {result.get('updates', {}).get('updatedCells', 0)} cells, "
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
        service = await self._get_sheets_service()
        spreadsheet_id = self._require_spreadsheet_id()

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

        range_name = f"{self._quote_sheet_name(self.REVIEW_SHEET_NAME)}!A{row}:H{row}"
        body = {
            "values": [row_values],
        }

        try:
            result = service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
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

    async def get_spreadsheet_id(self) -> str | None:
        """
        Get configured spreadsheet ID.

        Returns:
            Spreadsheet ID string or None if not configured
        """
        return self.spreadsheet_id