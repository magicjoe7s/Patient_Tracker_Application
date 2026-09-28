"""Qt item models that preserve stable domain identifiers."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPersistentModelIndex, Qt, Signal

Identifier = str | UUID
EMPTY_INDEX = QModelIndex()


@dataclass(frozen=True, slots=True)
class ListRow:
    """Immutable display row with identity independent of text and position."""

    identifier: Identifier
    primary: str
    secondary: str = ""
    checked: bool | None = None


class StableListModel(QAbstractListModel):
    """Reusable compact list model that stores stable identifiers."""

    IdentifierRole = Qt.ItemDataRole.UserRole + 1
    SecondaryRole = Qt.ItemDataRole.UserRole + 2
    check_state_changed = Signal(object, bool)

    def __init__(self, rows: Iterable[ListRow] = ()) -> None:
        super().__init__()
        self._rows = tuple(rows)
        self._movable = False

    def set_movable(self, movable: bool) -> None:
        self._movable = movable

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = EMPTY_INDEX) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> object:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return row.primary if not row.secondary else f"{row.primary}\n{row.secondary}"
        if role == self.IdentifierRole:
            return row.identifier
        if role == self.SecondaryRole:
            return row.secondary
        if role == Qt.ItemDataRole.AccessibleTextRole:
            return f"{row.primary} {row.secondary}".strip()
        if role == Qt.ItemDataRole.CheckStateRole and row.checked is not None:
            return Qt.CheckState.Checked if row.checked else Qt.CheckState.Unchecked
        return None

    def flags(self, index: QModelIndex | QPersistentModelIndex) -> Qt.ItemFlag:
        flags = super().flags(index)
        if self._movable:
            flags |= Qt.ItemFlag.ItemIsDropEnabled
            if index.isValid():
                flags |= Qt.ItemFlag.ItemIsDragEnabled
        if index.isValid() and self._rows[index.row()].checked is not None:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def setData(
        self,
        index: QModelIndex | QPersistentModelIndex,
        value: object,
        role: int = Qt.ItemDataRole.EditRole,
    ) -> bool:
        if (
            role != Qt.ItemDataRole.CheckStateRole
            or not index.isValid()
            or not 0 <= index.row() < len(self._rows)
        ):
            return False
        current = self._rows[index.row()]
        if current.checked is None:
            return False
        checked = value in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)
        if checked == current.checked:
            return True
        rows = list(self._rows)
        rows[index.row()] = ListRow(
            current.identifier, current.primary, current.secondary, checked
        )
        self._rows = tuple(rows)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        self.check_state_changed.emit(current.identifier, checked)
        return True

    def supportedDropActions(self) -> Qt.DropAction:
        return Qt.DropAction.MoveAction if self._movable else super().supportedDropActions()

    def moveRows(
        self,
        source_parent: QModelIndex | QPersistentModelIndex,
        source_row: int,
        count: int,
        destination_parent: QModelIndex | QPersistentModelIndex,
        destination_child: int,
    ) -> bool:
        if (
            not self._movable
            or source_parent.isValid()
            or destination_parent.isValid()
            or count < 1
            or source_row < 0
            or source_row + count > len(self._rows)
            or destination_child < 0
            or destination_child > len(self._rows)
            or source_row <= destination_child <= source_row + count
        ):
            return False
        self.beginMoveRows(
            source_parent, source_row, source_row + count - 1, destination_parent, destination_child
        )
        rows = list(self._rows)
        moving = rows[source_row : source_row + count]
        del rows[source_row : source_row + count]
        adjusted = (
            destination_child - count if destination_child > source_row else destination_child
        )
        rows[adjusted:adjusted] = moving
        self._rows = tuple(rows)
        self.endMoveRows()
        return True

    def identifiers(self) -> tuple[Identifier, ...]:
        return tuple(row.identifier for row in self._rows)

    def replace(self, rows: Iterable[ListRow]) -> None:
        self.beginResetModel()
        self._rows = tuple(rows)
        self.endResetModel()

    def identifier(self, index: QModelIndex) -> Identifier | None:
        value = self.data(index, self.IdentifierRole)
        return value if isinstance(value, (str, UUID)) else None

    def index_for(self, identifier: Identifier | None) -> QModelIndex:
        if identifier is None:
            return QModelIndex()
        for position, row in enumerate(self._rows):
            if row.identifier == identifier:
                return self.index(position, 0)
        return QModelIndex()
