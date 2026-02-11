"""
Incremental JSON response_text extractor for streaming.

When an LLM streams a JSON response containing a ``response_text`` field,
this utility extracts the text content character-by-character as it arrives
so it can be forwarded to the user immediately, without waiting for the
entire JSON payload to complete.

Usage::

    extractor = ResponseTextExtractor()
    for chunk in llm_stream:
        delta = extractor.feed(chunk)
        if delta:
            send_to_user(delta)
    # After stream ends, extractor.buffer has the full raw JSON
"""

from __future__ import annotations


class ResponseTextExtractor:
    """
    State-machine parser that incrementally extracts the value of the
    ``"response_text"`` key from a streaming JSON string.

    States:
        _SEEKING_KEY   – scanning for the key ``"response_text"``
        _SEEKING_COLON – found the key, waiting for ``:``
        _SEEKING_QUOTE – found the colon, waiting for opening ``"``
        _INSIDE_VALUE  – inside the string value, yielding characters
        _DONE          – value fully extracted
    """

    _SEEKING_KEY = 0
    _SEEKING_COLON = 1
    _SEEKING_QUOTE = 2
    _INSIDE_VALUE = 3
    _DONE = 4

    _KEY = '"response_text"'

    def __init__(self) -> None:
        self.buffer: str = ""          # Full raw JSON accumulated
        self._state: int = self._SEEKING_KEY
        self._key_scan_pos: int = 0    # How far we've matched the key
        self._escape_next: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def feed(self, chunk: str) -> str:
        """
        Feed a new chunk of raw JSON and return any new ``response_text``
        characters found in this chunk.

        Returns an empty string when no new text characters are available.
        """
        self.buffer += chunk
        if self._state == self._DONE:
            return ""

        delta_parts: list[str] = []

        for ch in chunk:
            if self._state == self._SEEKING_KEY:
                self._match_key_char(ch)

            elif self._state == self._SEEKING_COLON:
                if ch == ":":
                    self._state = self._SEEKING_QUOTE

            elif self._state == self._SEEKING_QUOTE:
                if ch == '"':
                    self._state = self._INSIDE_VALUE

            elif self._state == self._INSIDE_VALUE:
                extracted = self._process_value_char(ch)
                if extracted is not None:
                    delta_parts.append(extracted)

        return "".join(delta_parts)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _match_key_char(self, ch: str) -> None:
        """Advance or reset the key-matching cursor."""
        if ch == self._KEY[self._key_scan_pos]:
            self._key_scan_pos += 1
            if self._key_scan_pos == len(self._KEY):
                self._state = self._SEEKING_COLON
        else:
            # Partial match failed – check if this char restarts the key
            if ch == self._KEY[0]:
                self._key_scan_pos = 1
            else:
                self._key_scan_pos = 0

    def _process_value_char(self, ch: str) -> str | None:
        """
        Process a character inside the string value.

        Returns the character to emit (after un-escaping), or ``None``
        when the closing quote is reached.
        """
        if self._escape_next:
            self._escape_next = False
            # Standard JSON escape sequences
            escape_map = {
                "n": "\n",
                "t": "\t",
                "r": "\r",
                '"': '"',
                "\\": "\\",
                "/": "/",
            }
            return escape_map.get(ch, ch)

        if ch == "\\":
            self._escape_next = True
            return None

        if ch == '"':
            self._state = self._DONE
            return None

        return ch
