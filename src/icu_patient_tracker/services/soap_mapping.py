"""Lossless canonical SOAP Markdown rendering and conservative parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

INPUT_TOKEN = "#INPUT#"


@dataclass(frozen=True, slots=True)
class SOAPDiagnosticResult:
    """One display-only diagnostic checklist row."""

    title: str
    result_text: str = ""
    completed: bool = False


@dataclass(frozen=True, slots=True)
class SOAPRenderContext:
    """Canonical structured values used by the pure Markdown renderer."""

    day_number: int
    calendar_date: date
    code_status: str
    clinical_trend: str
    one_liner: str = ""
    problems: tuple[str, ...] = ()
    physical_examination: str = ""
    diagnostic_summary: str = ""
    diagnostic_results: tuple[SOAPDiagnosticResult, ...] = ()
    treatment_changes: str = ""
    instrumentation: tuple[str, ...] = ()
    device_output_labels: tuple[str, ...] = ()
    assessment: str = ""
    daytime_resident: str = ""
    overnight_resident: str = ""
    faculty: str = ""


@dataclass(frozen=True, slots=True)
class ParsedSOAP:
    """Recognized SOAP values; missing headings remain distinguishable from empty sections."""

    code_status: str | None = None
    clinical_trend: str | None = None
    one_liner: str | None = None
    problems: tuple[str, ...] | None = None
    physical_examination: str | None = None
    diagnostic_summary: str | None = None
    treatment_changes: str | None = None
    instrumentation: tuple[str, ...] | None = None
    assessment: str | None = None
    overnight_resident: str | None = None
    faculty: str | None = None


class CanonicalSOAPMapper:
    """Render and parse the tracker reference template without destructive rewrites."""

    _PROBLEM_HEADER = re.compile(r"^##\s*\*\*Problem list\*\*\s*$", re.IGNORECASE)
    _EXAM_HEADER = re.compile(
        r"^##\s*\*\*(?:Pertinent Exam Findings|Vitals/PE)\*\*\s*$", re.IGNORECASE
    )
    _DIAGNOSTIC_HEADER = re.compile(r"^\*\*Diagnostic Summary\*\*\s*$", re.IGNORECASE)
    _TREATMENT_HEADER = re.compile(r"^\*\*Treatment changes\*\*\s*$", re.IGNORECASE)
    _INSTRUMENTATION_HEADER = re.compile(r"^\*\*(?:Instrumentation|Lines):\*\*\s*$", re.IGNORECASE)
    _INS_OUT_HEADER = re.compile(r"^\*\*Ins/Out:\*\*\s*$", re.IGNORECASE)
    _ASSESSMENT_HEADER = re.compile(r"^##\s*\*\*Assessment\*\*\s*$", re.IGNORECASE)
    _AM_COLON = re.compile(r"^\*\*AM:\*\*\s*$", re.IGNORECASE)
    _PM_COLON = re.compile(r"^\*\*PM:\*\*\s*$", re.IGNORECASE)
    _AM = re.compile(r"^\*\*AM\*\*\s*$", re.IGNORECASE)
    _PM = re.compile(r"^\*\*PM\*\*\s*$", re.IGNORECASE)
    _AM_ITALIC = re.compile(r"^\*AM\*\s*$", re.IGNORECASE)
    _PM_ITALIC = re.compile(r"^\*PM\*\s*$", re.IGNORECASE)

    def render(self, context: SOAPRenderContext) -> str:
        """Create a complete canonical document following the reference section order."""
        next_date = context.calendar_date + timedelta(days=1)
        lines = [
            f"# Day #INPUT# ICU hospitalization #INPUT# "
            f"{context.calendar_date:%m/%d/%Y} - 9am {next_date:%m/%d/%Y}",
            f"**Code Status:** {context.code_status.strip() or INPUT_TOKEN}",
            f"**Clinical Trend:** {context.clinical_trend.strip() or INPUT_TOKEN}",
            "",
            "---",
            f"**One Liner:** {INPUT_TOKEN}",
            "",
            "---",
            "## **Problem list**",
            f"1. {INPUT_TOKEN}",
            "",
            "---",
            "## **Pertinent exam findings**",
            "**AM:**",
            f"- {INPUT_TOKEN}",
            "",
            "**PM:**",
            f"- {INPUT_TOKEN}",
            "",
            "---",
            "**Diagnostic Summary**",
            f"- {INPUT_TOKEN}",
            "",
            "**Treatment changes**",
            f"- {INPUT_TOKEN}",
            "",
            "**instrumentation:**",
            "",
            "**Ins/Out:**",
            "- *IVF:* #INPUT#",
            "- *Medications:* #INPUT#",
            "- *Diet:* #INPUT#",
            "",
            "---",
            "",
            "## **Assessment**",
            "**AM**",
            f"- {INPUT_TOKEN}",
            "",
            "**PM**",
            f"- {INPUT_TOKEN}",
            "",
            "## **Recommendations**",
            "*Diagnostics*",
            f"- {INPUT_TOKEN}",
            "",
            "*Therapies*",
            f"- {INPUT_TOKEN}",
            "",
            "---",
            "",
            "*Daytime primary ICU resident:* "
            f"{context.daytime_resident.strip() or 'Joseph Evans, D.V.M.'}",
            f"*Overnight ICU Resident:* {INPUT_TOKEN}",
            f"*Faculty:* {INPUT_TOKEN}",
        ]
        return "\n".join(lines)

    def refresh(self, markdown: str, context: SOAPRenderContext, sections: tuple[str, ...]) -> str:
        """Replace only explicitly selected mapped regions and preserve all other bytes."""
        allowed = {
            "meta",
            "one_liner",
            "problem_list",
            "physical_examination",
            "diagnostics",
            "treatment_changes",
            "instrumentation",
            "assessment",
            "staff",
        }
        if not sections or set(sections) - allowed:
            raise ValueError("SOAP refresh sections must be recognized and non-empty.")
        if not markdown.strip():
            return self.render(context)

        result = markdown
        newline = "\r\n" if "\r\n" in markdown else "\n"
        if "meta" in sections:
            result = self._replace_single(
                result,
                r"^.*\*\*Code Status:\*\*.*$",
                f"**Code Status:** {context.code_status}",
            )
            result = self._replace_single(
                result,
                r"^.*\*\*Clinical Trend:\*\*.*$",
                f"**Clinical Trend:** {context.clinical_trend}",
            )
        if "one_liner" in sections:
            result = self._replace_single(
                result,
                r"^\*\*One Liner:\*\*.*$",
                f"**One Liner:** {context.one_liner.strip() or INPUT_TOKEN}",
            )
        if "problem_list" in sections:
            result = self._replace_block(
                result,
                self._PROBLEM_HEADER,
                (re.compile(r"^---$"), re.compile(r"^##\s")),
                ["## **Problem list**", *self._problem_lines(context.problems), ""],
                newline,
            )
        if "physical_examination" in sections:
            result = self._replace_nested_block(
                result,
                self._EXAM_HEADER,
                self._AM_COLON,
                self._PM_COLON,
                ["**AM:**", *self._text_bullets(context.physical_examination), ""],
                newline,
            )
        if "diagnostics" in sections:
            result_lines = self._diagnostic_result_lines(context.diagnostic_results)
            summary_lines = (
                self._text_bullets(context.diagnostic_summary)
                if context.diagnostic_summary.strip() or not result_lines
                else []
            )
            result = self._replace_block(
                result,
                self._DIAGNOSTIC_HEADER,
                (self._TREATMENT_HEADER, re.compile(r"^---$"), re.compile(r"^##\s")),
                [
                    "**Diagnostic Summary**",
                    *result_lines,
                    *summary_lines,
                    "",
                ],
                newline,
            )
        if "treatment_changes" in sections:
            if self._has_nested_block(
                result, self._TREATMENT_HEADER, self._AM_ITALIC, self._PM_ITALIC
            ):
                result = self._replace_nested_block(
                    result,
                    self._TREATMENT_HEADER,
                    self._AM_ITALIC,
                    self._PM_ITALIC,
                    ["*AM*", *self._text_bullets(context.treatment_changes), ""],
                    newline,
                )
            else:
                result = self._replace_block(
                    result,
                    self._TREATMENT_HEADER,
                    (
                        self._INSTRUMENTATION_HEADER,
                        re.compile(r"^---$"),
                        re.compile(r"^##\s"),
                    ),
                    ["**Treatment changes**", *self._text_bullets(context.treatment_changes), ""],
                    newline,
                )
        if "instrumentation" in sections:
            values = list(context.instrumentation)
            result = self._replace_block(
                result,
                self._INSTRUMENTATION_HEADER,
                (self._INS_OUT_HEADER, re.compile(r"^---$"), re.compile(r"^##\s")),
                ["**instrumentation:**", *values, ""],
                newline,
            )
            result = self._sync_device_outputs(result, context.device_output_labels, newline)
        if "assessment" in sections:
            result = self._replace_nested_block(
                result,
                self._ASSESSMENT_HEADER,
                self._AM,
                self._PM,
                ["**AM**", *self._text_bullets(context.assessment), ""],
                newline,
            )
        if "staff" in sections:
            result = self._replace_single(
                result,
                r"^\*Daytime primary ICU resident:\*.*$",
                f"*Daytime primary ICU resident:* "
                f"{context.daytime_resident.strip() or INPUT_TOKEN}",
            )
            result = self._replace_single(
                result,
                r"^\*(?:Overnight primary ICU resident|Overnight ICU Resident):\*.*$",
                f"*Overnight ICU Resident:* {context.overnight_resident.strip() or INPUT_TOKEN}",
            )
            result = self._replace_single(
                result,
                r"^\*Faculty:\*.*$",
                f"*Faculty:* {context.faculty.strip() or INPUT_TOKEN}",
            )
        return result

    def parse(self, markdown: str) -> ParsedSOAP:
        """Extract only confidently recognized fields; unknown text is ignored, never discarded."""
        code_status = self._single_value(markdown, r"^\*\*Code Status:\*\*\s*(.*)$")
        clinical_trend = self._single_value(markdown, r"^\*\*Clinical Trend:\*\*\s*(.*)$")
        one_liner = self._single_value(markdown, r"^\*\*One Liner:\*\*\s*(.*)$")
        overnight = self._single_value(
            markdown,
            r"^\*(?:Overnight primary ICU resident|Overnight ICU Resident):\*\s*(.*)$",
        )
        faculty = self._single_value(markdown, r"^\*Faculty:\*\s*(.*)$")
        problems = self._parse_problem_titles(markdown)
        diagnostic_summary = self._parse_diagnostic_summary(
            markdown,
            self._DIAGNOSTIC_HEADER,
            (self._TREATMENT_HEADER,),
        )
        treatment = (
            self._parse_nested_text(
                markdown,
                self._TREATMENT_HEADER,
                self._AM_ITALIC,
                self._PM_ITALIC,
            )
            if self._has_nested_block(
                markdown,
                self._TREATMENT_HEADER,
                self._AM_ITALIC,
                self._PM_ITALIC,
            )
            else self._parse_text_block(
                markdown, self._TREATMENT_HEADER, (self._INSTRUMENTATION_HEADER,)
            )
        )
        instrumentation = self._parse_simple_block(
            markdown, self._INSTRUMENTATION_HEADER, stop_patterns=(self._INS_OUT_HEADER,)
        )
        physical = self._parse_nested_text(
            markdown, self._EXAM_HEADER, self._AM_COLON, self._PM_COLON
        )
        assessment = self._parse_nested_text(markdown, self._ASSESSMENT_HEADER, self._AM, self._PM)
        return ParsedSOAP(
            code_status=code_status,
            clinical_trend=clinical_trend,
            one_liner=one_liner,
            problems=problems,
            physical_examination=physical,
            diagnostic_summary=diagnostic_summary,
            treatment_changes=treatment,
            instrumentation=instrumentation,
            assessment=assessment,
            overnight_resident=overnight,
            faculty=faculty,
        )

    @staticmethod
    def _bullets(values: tuple[str, ...], prefix: str = "- ") -> list[str]:
        return [f"{prefix}{value}" for value in values] if values else [f"{prefix}{INPUT_TOKEN}"]

    @staticmethod
    def _problem_lines(values: tuple[str, ...]) -> list[str]:
        if not values:
            return [f"1. {INPUT_TOKEN}"]
        lines: list[str] = []
        for number, value in enumerate(values, 1):
            parts = tuple(line.strip() for line in value.splitlines() if line.strip())
            if not parts:
                continue
            lines.append(f"{number}. {parts[0]}")
            lines.extend(f"   - {detail}" for detail in parts[1:])
        return lines or [f"1. {INPUT_TOKEN}"]

    @classmethod
    def _text_bullets(cls, value: str) -> list[str]:
        values = tuple(line.strip() for line in value.splitlines() if line.strip())
        return cls._bullets(values)

    @staticmethod
    def _diagnostic_result_lines(values: tuple[SOAPDiagnosticResult, ...]) -> list[str]:
        lines: list[str] = []
        for value in values:
            marker = "x" if value.completed else " "
            title = value.title.strip().rstrip(":")
            result = " ".join(value.result_text.split())
            suffix = f": {result}" if result else ""
            lines.append(f"- [{marker}] {title}{suffix}")
        return lines

    @staticmethod
    def _replace_single(markdown: str, pattern: str, replacement: str) -> str:
        return re.sub(pattern, replacement, markdown, count=1, flags=re.IGNORECASE | re.MULTILINE)

    @classmethod
    def _replace_block(
        cls,
        markdown: str,
        start: re.Pattern[str],
        stops: tuple[re.Pattern[str], ...],
        replacement: list[str],
        newline: str,
    ) -> str:
        lines = markdown.splitlines(keepends=True)
        start_index = cls._find_line(lines, start)
        if start_index is None:
            return markdown
        end_index = len(lines)
        for index in range(start_index + 1, len(lines)):
            stripped = lines[index].strip()
            if any(stop.match(stripped) for stop in stops):
                end_index = index
                break
        rendered = newline.join(replacement)
        if end_index < len(lines) or lines[start_index].endswith(("\n", "\r")):
            rendered += newline
        return "".join(lines[:start_index]) + rendered + "".join(lines[end_index:])

    @classmethod
    def _replace_nested_block(
        cls,
        markdown: str,
        outer: re.Pattern[str],
        start: re.Pattern[str],
        stop: re.Pattern[str],
        replacement: list[str],
        newline: str,
    ) -> str:
        lines = markdown.splitlines(keepends=True)
        outer_index = cls._find_line(lines, outer)
        if outer_index is None:
            return markdown
        start_index = cls._find_line(lines, start, outer_index + 1)
        stop_index = cls._find_line(lines, stop, (start_index or outer_index) + 1)
        if start_index is None or stop_index is None:
            return markdown
        rendered = newline.join(replacement) + newline
        return "".join(lines[:start_index]) + rendered + "".join(lines[stop_index:])

    @staticmethod
    def _find_line(lines: list[str], pattern: re.Pattern[str], start: int = 0) -> int | None:
        for index in range(start, len(lines)):
            if pattern.match(lines[index].strip()):
                return index
        return None

    @classmethod
    def _has_nested_block(
        cls,
        markdown: str,
        outer: re.Pattern[str],
        start: re.Pattern[str],
        stop: re.Pattern[str],
    ) -> bool:
        lines = markdown.splitlines()
        outer_index = cls._find_line(lines, outer)
        if outer_index is None:
            return False
        start_index = cls._find_line(lines, start, outer_index + 1)
        return start_index is not None and cls._find_line(lines, stop, start_index + 1) is not None

    @classmethod
    def _block_lines(
        cls,
        markdown: str,
        start: re.Pattern[str],
        stops: tuple[re.Pattern[str], ...] = (),
    ) -> list[str] | None:
        lines = markdown.splitlines()
        start_index = cls._find_line(lines, start)
        if start_index is None:
            return None
        result: list[str] = []
        for line in lines[start_index + 1 :]:
            stripped = line.strip()
            if (
                any(stop.match(stripped) for stop in stops)
                or stripped == "---"
                or stripped.startswith("## ")
            ):
                break
            result.append(line)
        return result

    @classmethod
    def _parse_simple_block(
        cls,
        markdown: str,
        start: re.Pattern[str],
        *,
        stop_at_heading: bool = False,
        stop_patterns: tuple[re.Pattern[str], ...] = (),
    ) -> tuple[str, ...] | None:
        del stop_at_heading
        lines = cls._block_lines(markdown, start, stop_patterns)
        if lines is None:
            return None
        values = tuple(cls._strip_bullet(line) for line in lines if cls._is_content(line))
        return values or None

    @classmethod
    def _parse_problem_titles(cls, markdown: str) -> tuple[str, ...] | None:
        """Read numbered problems together with their indented supporting details."""
        lines = cls._block_lines(markdown, cls._PROBLEM_HEADER, ())
        if lines is None:
            return None
        values: list[str] = []
        current: list[str] = []

        def finish() -> None:
            if current:
                values.append("\n".join(current))
                current.clear()

        for line in lines:
            numbered = re.match(r"^\s*\d+[.)]\s+(.+?)\s*$", line)
            legacy = re.match(r"^[-*+]\s+(.+?)\s*$", line)
            match = numbered or legacy
            if match and match.group(1) != INPUT_TOKEN:
                finish()
                current.append(match.group(1).strip())
                continue
            detail = re.match(r"^\s+[-*+•]\s+(.+?)\s*$", line)
            if detail and current and detail.group(1) != INPUT_TOKEN:
                current.append(detail.group(1).strip())
        finish()
        return tuple(values) or None

    @classmethod
    def _parse_text_block(
        cls, markdown: str, start: re.Pattern[str], stops: tuple[re.Pattern[str], ...]
    ) -> str | None:
        lines = cls._block_lines(markdown, start, stops)
        if lines is None:
            return None
        values = tuple(cls._strip_bullet(line) for line in lines if cls._is_content(line))
        return "\n".join(values) if values else None

    @classmethod
    def _parse_nested_text(
        cls,
        markdown: str,
        outer: re.Pattern[str],
        start: re.Pattern[str],
        stop: re.Pattern[str],
    ) -> str | None:
        lines = markdown.splitlines()
        outer_index = cls._find_line(lines, outer)
        if outer_index is None:
            return None
        start_index = cls._find_line(lines, start, outer_index + 1)
        if start_index is None:
            return None
        stop_index = cls._find_line(lines, stop, start_index + 1)
        if stop_index is None:
            return None
        values = tuple(
            cls._strip_bullet(line)
            for line in lines[start_index + 1 : stop_index]
            if cls._is_content(line)
        )
        return "\n".join(values) if values else None

    @staticmethod
    def _strip_bullet(line: str) -> str:
        return re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", "", line).strip()

    @staticmethod
    def _is_content(line: str) -> bool:
        stripped = line.strip()
        return bool(stripped and INPUT_TOKEN not in stripped)

    @classmethod
    def _parse_diagnostic_summary(
        cls,
        markdown: str,
        start: re.Pattern[str],
        stops: tuple[re.Pattern[str], ...],
    ) -> str | None:
        """Parse free text while leaving structured checklist rows untouched."""
        lines = cls._block_lines(markdown, start, stops)
        if lines is None:
            return None
        content = tuple(
            line
            for line in lines
            if cls._is_content(line) and not re.match(r"^\s*[-*+]?\s*\[[ x]\]", line, re.I)
        )
        values = tuple(cls._strip_bullet(line) for line in content)
        return "\n".join(values) if values else None

    @staticmethod
    def _single_value(markdown: str, pattern: str) -> str | None:
        match = re.search(pattern, markdown, re.IGNORECASE | re.MULTILINE)
        if match is None:
            return None
        value = " ".join(match.group(1).split())
        return None if value == INPUT_TOKEN else value

    @classmethod
    def _sync_device_outputs(
        cls, markdown: str, active_labels: tuple[str, ...], newline: str
    ) -> str:
        lines = markdown.splitlines(keepends=True)
        header = cls._find_line(lines, cls._INS_OUT_HEADER)
        if header is None:
            return markdown
        end = len(lines)
        for index in range(header + 1, len(lines)):
            if lines[index].strip() in {"---"} or lines[index].strip().startswith("## "):
                end = index
                break
        output_pattern = re.compile(
            r"^[-*+]\s+\*((?:UOP|Urinary catheter|Fecal foley|Drain|Chest tube|"
            r"Drain production|Chest tube production|[^*]+\soutput)):?\*\s*[-:]\s*(.*)$",
            re.I,
        )
        saved: dict[str, str] = {}
        kept: list[str] = []
        insert_at = 0
        for line in lines[header + 1 : end]:
            match = output_pattern.match(line.strip())
            if match:
                if match.group(2).strip() != INPUT_TOKEN:
                    saved[match.group(1).casefold()] = match.group(2).strip()
                continue
            kept.append(line.rstrip("\r\n"))
            if re.match(r"^[-*+]\s+\*Diet:\*", line.strip(), re.I):
                insert_at = len(kept)
        rows = [
            f"- *{label}* - {saved.get(label.casefold(), INPUT_TOKEN)}" for label in active_labels
        ]
        for label, value in saved.items():
            canonical = next((item for item in active_labels if item.casefold() == label), None)
            if canonical is None:
                display = {"uop": "UOP"}.get(label, label.title())
                rows.append(f"- *{display}* - {value}")
        rebuilt = kept[:insert_at] + rows + kept[insert_at:]
        rendered = newline.join(rebuilt)
        if end < len(lines):
            rendered += newline
        return "".join(lines[: header + 1]) + rendered + "".join(lines[end:])
