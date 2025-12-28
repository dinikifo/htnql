import sys
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QListWidget, QListWidgetItem, QFormLayout, QLineEdit,
    QSpinBox, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QPlainTextEdit, QTabWidget, QFileDialog, QLabel, QMessageBox,
    QDialog, QDialogButtonBox, QComboBox
)
from sqlalchemy import create_engine, MetaData

# ---- HTNQL imports: adjust if your package differs ----
from htnql.schema_graph import SchemaGraph
from htnql.query_engine import QueryEngine
from htnql.report_spec import ReportSpec, MetricSpec, FilterSpec
from htnql.shape_suggestion import ShapeIntent, suggest_shapes


# ============================================================
#  Session layer (no Qt here) – wraps HTNQL
# ============================================================

class HTNQLSession:
    """
    Thin wrapper around your HTNQL primitives.

    - Reflects the DB via SQLAlchemy
    - Builds SchemaGraph + QueryEngine
    - Exposes schema & query methods for the GUI
    """
    def __init__(self, url: str):
        self.url = url
        self.engine = create_engine(url)
        md = MetaData()
        md.reflect(bind=self.engine)
        self.schema_graph = SchemaGraph(md)
        self.qe = QueryEngine(self.engine, self.schema_graph)

    # ---------- schema ----------
    def list_tables(self):
        tables = []
        for name, table in self.schema_graph.metadata.tables.items():
            columns = []
            for col in table.columns:
                columns.append({
                    "name": col.name,
                    "type": str(col.type),
                })
            tables.append({"name": name, "columns": columns})
        return tables

    def get_columns_for_table(self, table: str):
        t = self.schema_graph.metadata.tables.get(table)
        if not t:
            return []
        return [{"name": c.name, "type": str(c.type)} for c in t.columns]

    def suggest_shapes_for_table(self, table: str):
        intent = ShapeIntent(include_tables=[table])
        candidates = suggest_shapes(self.schema_graph, intent)
        return [asdict(c) for c in candidates]

    # ---------- running queries ----------
    def run_report(self, spec_dict: dict):
        spec = ReportSpec(
            name=spec_dict.get("name", "ad_hoc"),
            metrics=[MetricSpec(**m) for m in spec_dict["metrics"]],
            group_by=spec_dict.get("group_by", []),
            filters=[FilterSpec(**f) for f in spec_dict.get("filters", [])],
            limit=spec_dict.get("limit"),
            base_sql=spec_dict.get("base_sql"),
            raw_sql=spec_dict.get("raw_sql"),
        )

        rows, trace = self.qe.run_report_with_trace(spec)

        rows_list = []
        headers = None

        for r in rows:
            # Case 1: dict-like row
            if isinstance(r, dict):
                if headers is None:
                    headers = list(r.keys())
                rows_list.append(list(r.values()))
            else:
                # Case 2: SQLAlchemy Row / namedtuple-like
                if headers is None and hasattr(r, "keys"):
                    try:
                        headers = list(r.keys())
                    except TypeError:
                        headers = None
                rows_list.append(list(r))

        return {
            "rows": rows_list,
            "headers": headers,
            "trace": [str(step) for step in trace],
        }



# ============================================================
#  Connection dialog (SQLite for now)
# ============================================================

class ConnectionDialog(QDialog):
    """
    Very simple: lets the user pick SQLite file, builds SQLAlchemy URL.
    You can extend this later for Postgres/MySQL etc.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Connect to Database")
        self.resize(400, 150)

        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["SQLite"])  # extend later as needed

        self.path_edit = QLineEdit()
        browse_btn = QPushButton("Browse…")

        form = QFormLayout()
        form.addRow("Backend:", self.backend_combo)

        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit)
        path_row.addWidget(browse_btn)
        form.addRow("SQLite file:", path_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            Qt.Horizontal,
            self,
        )

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        browse_btn.clicked.connect(self.on_browse)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

    def on_browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open SQLite DB", "", "SQLite Files (*.db *.sqlite *.sqlite3);;All Files (*)"
        )
        if path:
            self.path_edit.setText(path)

    def build_url(self) -> str | None:
        backend = self.backend_combo.currentText()
        if backend == "SQLite":
            p = self.path_edit.text().strip()
            if not p:
                return None
            return f"sqlite:///{Path(p).absolute()}"
        # future: support other backends
        return None


# ============================================================
#  Schema browser (left panel)
# ============================================================

class SchemaBrowser(QWidget):
    """
    Shows list of tables. Clicking one emits a signal by calling a handler
    set from MainWindow (to avoid custom signals for simplicity).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.list = QListWidget()

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Tables"))
        layout.addWidget(self.list)

        # callback set by MainWindow
        self.on_table_selected = None

        self.list.itemClicked.connect(self._item_clicked)

    def set_schema(self, tables):
        self.list.clear()
        for t in tables:
            item = QListWidgetItem(t["name"])
            item.setData(Qt.UserRole, t)
            self.list.addItem(item)

    def _item_clicked(self, item: QListWidgetItem):
        data = item.data(Qt.UserRole)
        if self.on_table_selected:
            self.on_table_selected(data["name"], data["columns"])


# ============================================================
#  Query builder (right-top panel)
# ============================================================

class QueryBuilder(QWidget):
    """
    Visual builder for a ReportSpec subset:

    - Choose base table
    - Metrics: a small table of expression + alias
    - Group by: list of columns with checkboxes
    - Filters: table of column/op/value
    - Limit
    - Optional shape suggestions (combo)
    """
    def __init__(self, parent=None):
        super().__init__(parent)

        # state
        self._current_table = None
        self._current_columns = []  # list of dicts {name, type}
        self._current_shapes = []   # list of dicts from suggest_shapes

        # --- top: base table + shape suggestions ---
        self.base_table_edit = QLineEdit()
        self.base_table_edit.setReadOnly(True)

        self.shape_combo = QComboBox()
        self.shape_combo.addItem("(No shape suggestion)")
        self.shape_combo.currentIndexChanged.connect(self.on_shape_selected)

        base_form = QFormLayout()
        base_form.addRow("Base table:", self.base_table_edit)
        base_form.addRow("Shape:", self.shape_combo)

        # --- metrics table ---
        self.metrics_table = QTableWidget(0, 2)
        self.metrics_table.setHorizontalHeaderLabels(["Expression", "Alias"])
        self.metrics_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.add_metric_btn = QPushButton("Add metric")
        self.remove_metric_btn = QPushButton("Remove selected metric")

        self.add_metric_btn.clicked.connect(self.add_metric_row)
        self.remove_metric_btn.clicked.connect(self.remove_selected_metric_row)

        metrics_layout = QVBoxLayout()
        metrics_layout.addWidget(QLabel("Metrics"))
        metrics_layout.addWidget(self.metrics_table)

        metrics_btn_row = QHBoxLayout()
        metrics_btn_row.addWidget(self.add_metric_btn)
        metrics_btn_row.addWidget(self.remove_metric_btn)
        metrics_layout.addLayout(metrics_btn_row)

        # --- group by list (checkboxes) ---
        self.group_by_table = QTableWidget(0, 2)
        self.group_by_table.setHorizontalHeaderLabels(["Use", "Column"])
        self.group_by_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)

        group_layout = QVBoxLayout()
        group_layout.addWidget(QLabel("Group by"))
        group_layout.addWidget(self.group_by_table)

        # --- filters table ---
        self.filters_table = QTableWidget(0, 3)
        self.filters_table.setHorizontalHeaderLabels(["Column", "Op", "Value"])
        self.filters_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        self.add_filter_btn = QPushButton("Add filter")
        self.remove_filter_btn = QPushButton("Remove selected filter")

        self.add_filter_btn.clicked.connect(self.add_filter_row)
        self.remove_filter_btn.clicked.connect(self.remove_selected_filter_row)

        filters_layout = QVBoxLayout()
        filters_layout.addWidget(QLabel("Filters"))
        filters_layout.addWidget(self.filters_table)
        filters_btn_row = QHBoxLayout()
        filters_btn_row.addWidget(self.add_filter_btn)
        filters_btn_row.addWidget(self.remove_filter_btn)
        filters_layout.addLayout(filters_btn_row)

        # --- bottom: limit + run ---
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 1_000_000)
        self.limit_spin.setValue(1000)

        self.run_btn = QPushButton("Run")

        bottom_form = QFormLayout()
        bottom_form.addRow("Limit:", self.limit_spin)
        bottom_form.addRow("", self.run_btn)

        # --- compose ---
        top_row = QHBoxLayout()
        top_row.addLayout(base_form)

        # metrics + group by + filters stacked
        middle_row = QHBoxLayout()
        middle_row.addLayout(metrics_layout, 2)
        middle_row.addLayout(group_layout, 1)
        middle_row.addLayout(filters_layout, 2)

        main_layout = QVBoxLayout(self)
        main_layout.addLayout(top_row)
        main_layout.addLayout(middle_row)
        main_layout.addLayout(bottom_form)

    # --------------------------------------------------------
    #  Base table & columns
    # --------------------------------------------------------
    def set_table_and_columns(self, table_name: str, columns: list[dict]):
        self._current_table = table_name
        self._current_columns = columns
        self.base_table_edit.setText(table_name)

        # reset group_by table
        self.group_by_table.setRowCount(0)
        for col in columns:
            row = self.group_by_table.rowCount()
            self.group_by_table.insertRow(row)

            # checkbox in column 0
            cb_item = QTableWidgetItem()
            cb_item.setFlags(cb_item.flags() | Qt.ItemIsUserCheckable)
            cb_item.setCheckState(Qt.Unchecked)
            self.group_by_table.setItem(row, 0, cb_item)

            # name in column 1
            name_item = QTableWidgetItem(col["name"])
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self.group_by_table.setItem(row, 1, name_item)

        # reset filters (column combobox options)
        self.filters_table.setRowCount(0)

        # clear shape combo; caller will set shapes separately
        self.shape_combo.blockSignals(True)
        self.shape_combo.clear()
        self.shape_combo.addItem("(No shape suggestion)")
        self.shape_combo.blockSignals(False)
        self._current_shapes = []

        # default metric row if none
        if self.metrics_table.rowCount() == 0:
            self.add_metric_row()

    # --------------------------------------------------------
    #  Shapes
    # --------------------------------------------------------
    def set_shapes(self, shapes: list[dict]):
        """
        shapes come from HTNQL's suggest_shapes, already as dicts.
        We only show 'description' in the UI.
        """
        self._current_shapes = shapes
        self.shape_combo.blockSignals(True)
        self.shape_combo.clear()
        self.shape_combo.addItem("(No shape suggestion)")
        for s in shapes:
            desc = s.get("description") or "(unnamed shape)"
            self.shape_combo.addItem(desc)
        self.shape_combo.blockSignals(False)

    def on_shape_selected(self, index: int):
        """
        When a shape is chosen, we *could* pre-fill metrics / group_by
        based on its base_sql or something else.
        For now, we'll just leave this as a hook.
        """
        if index <= 0:
            return
        shape = self._current_shapes[index - 1]
        # Example: you might store shape['base_sql'] somewhere
        # or pre-fill metrics based on shape['tables'] or similar.
        # Here we only set a status in group_by or leave it as a no-op.
        # You can implement your own heuristics here if desired.
        # TODO: Implement if you want shape-based auto-filling.
        _ = shape  # avoid unused warning for now

    # --------------------------------------------------------
    #  Metrics
    # --------------------------------------------------------
    def add_metric_row(self):
        row = self.metrics_table.rowCount()
        self.metrics_table.insertRow(row)
        # expr
        self.metrics_table.setItem(row, 0, QTableWidgetItem("COUNT(*)" if row == 0 else ""))
        # alias
        self.metrics_table.setItem(row, 1, QTableWidgetItem("count" if row == 0 else ""))

    def remove_selected_metric_row(self):
        row = self.metrics_table.currentRow()
        if row >= 0:
            self.metrics_table.removeRow(row)

    # --------------------------------------------------------
    #  Filters
    # --------------------------------------------------------
    def add_filter_row(self):
        row = self.filters_table.rowCount()
        self.filters_table.insertRow(row)

        # Column combobox
        col_combo = QComboBox()
        for col in self._current_columns:
            col_combo.addItem(col["name"])
        self.filters_table.setCellWidget(row, 0, col_combo)

        # Op combobox
        op_combo = QComboBox()
        op_combo.addItems(["=", "!=", "<", "<=", ">", ">=", "LIKE", "IN", "BETWEEN"])
        self.filters_table.setCellWidget(row, 1, op_combo)

        # Value as plain text
        self.filters_table.setItem(row, 2, QTableWidgetItem(""))

    def remove_selected_filter_row(self):
        row = self.filters_table.currentRow()
        if row >= 0:
            self.filters_table.removeRow(row)

    # --------------------------------------------------------
    #  Build ReportSpec dict for the session
    # --------------------------------------------------------
    def build_spec_dict(self):
        # base table
        base_table = self._current_table or ""
        base_sql = None
        if base_table:
            base_sql = f"SELECT * FROM {base_table}"

        # metrics
        metrics = []
        for row in range(self.metrics_table.rowCount()):
            expr_item = self.metrics_table.item(row, 0)
            alias_item = self.metrics_table.item(row, 1)
            expr = expr_item.text().strip() if expr_item else ""
            alias = alias_item.text().strip() if alias_item else ""
            if expr:
                metrics.append({"expr": expr, "alias": alias or f"metric_{row}"})

        if not metrics:
            # fallback: a count(*)
            metrics = [{"expr": "COUNT(*)", "alias": "count"}]

        # group_by
        group_by = []
        for row in range(self.group_by_table.rowCount()):
            cb_item = self.group_by_table.item(row, 0)
            name_item = self.group_by_table.item(row, 1)
            if cb_item and cb_item.checkState() == Qt.Checked and name_item:
                col_name = name_item.text().strip()
                if col_name:
                    # Qualify with table if we have one
                    if base_table:
                        group_by.append(f"{base_table}.{col_name}")
                    else:
                        group_by.append(col_name)

        # filters
        filters = []
        for row in range(self.filters_table.rowCount()):
            col_widget = self.filters_table.cellWidget(row, 0)
            op_widget = self.filters_table.cellWidget(row, 1)
            val_item = self.filters_table.item(row, 2)

            if not col_widget or not op_widget:
                continue

            col_name = col_widget.currentText().strip()
            op = op_widget.currentText().strip()
            val = val_item.text().strip() if val_item else ""

            if col_name and op and val:
                # You can add type handling here (ints/dates etc.).
                filters.append({
                    "column": f"{base_table}.{col_name}" if base_table else col_name,
                    "op": op,
                    "value": val,
                })

        spec_dict = {
            "name": f"gui_{base_table or 'query'}",
            "metrics": metrics,
            "group_by": group_by,
            "filters": filters,
            "limit": self.limit_spin.value(),
            "base_sql": base_sql,
        }
        return spec_dict


# ============================================================
#  Results panel (right-bottom)
# ============================================================

class ResultView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        self.debug_text = QPlainTextEdit()
        self.debug_text.setReadOnly(True)

        tabs = QTabWidget()
        tabs.addTab(self.table, "Results")
        tabs.addTab(self.debug_text, "Plan / Debug")

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)

    def set_rows(self, rows, headers=None):
        self.table.clear()
        if not rows:
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            return

        n_rows = len(rows)
        n_cols = len(rows[0])
        self.table.setRowCount(n_rows)
        self.table.setColumnCount(n_cols)

        if headers and len(headers) == n_cols:
            self.table.setHorizontalHeaderLabels(headers)

        for i, row in enumerate(rows):
            for j, val in enumerate(row):
                item = QTableWidgetItem(str(val))
                self.table.setItem(i, j, item)

    def set_debug_text(self, text: str):
        self.debug_text.setPlainText(text)


# ============================================================
#  Main window
# ============================================================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HTNQL Query Builder (PySide6)")
        self.resize(1400, 900)

        self.session: HTNQLSession | None = None
        self._tables_cache = []  # list from session.list_tables()

        # Widgets
        self.schema_browser = SchemaBrowser()
        self.query_builder = QueryBuilder()
        self.result_view = ResultView()

        # wiring for table selection callback
        self.schema_browser.on_table_selected = self.on_table_selected

        # Layout with splitters
        right_splitter = QSplitter(Qt.Vertical)
        right_splitter.addWidget(self.query_builder)
        right_splitter.addWidget(self.result_view)
        right_splitter.setStretchFactor(0, 0)
        right_splitter.setStretchFactor(1, 1)

        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.addWidget(self.schema_browser)
        main_splitter.addWidget(right_splitter)
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 1)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.addWidget(main_splitter)
        self.setCentralWidget(central)

        # Menus / toolbar
        self._setup_menu()

        # Signals
        self.query_builder.run_btn.clicked.connect(self.on_run_clicked)

        self.statusBar().showMessage("No database connected")

    # ---------- Menus ----------
    def _setup_menu(self):
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")

        open_action = QAction("Connect…", self)
        open_action.triggered.connect(self.action_connect)
        file_menu.addAction(open_action)

        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

    # ---------- Actions ----------
    def action_connect(self):
        dlg = ConnectionDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        url = dlg.build_url()
        if not url:
            QMessageBox.warning(self, "Missing info", "Please select a database.")
            return

        try:
            session = HTNQLSession(url)
        except Exception as e:
            QMessageBox.critical(self, "Connection error", str(e))
            return

        self.session = session
        self.statusBar().showMessage(f"Connected to {url}", 5000)
        self.load_schema()

    def load_schema(self):
        if not self.session:
            return
        try:
            tables = self.session.list_tables()
        except Exception as e:
            QMessageBox.critical(self, "Schema error", str(e))
            return
        self._tables_cache = tables
        self.schema_browser.set_schema(tables)

    # ---------- Schema selection ----------
    def on_table_selected(self, table_name: str, columns: list[dict]):
        self.query_builder.set_table_and_columns(table_name, columns)

        # ask session for shape suggestions
        if self.session:
            try:
                shapes = self.session.suggest_shapes_for_table(table_name)
            except Exception:
                shapes = []
            self.query_builder.set_shapes(shapes)

    # ---------- Run query ----------
    def on_run_clicked(self):
        if not self.session:
            QMessageBox.warning(self, "No DB", "Please connect to a database first.")
            return

        spec = self.query_builder.build_spec_dict()

        result = self.session.run_report(spec)
        rows = result["rows"]
        headers = result.get("headers")
        self.result_view.set_rows(rows, headers=headers)

        debug_text = "Trace:\n" + "\n".join(result["trace"])
        self.result_view.set_debug_text(debug_text)



# ============================================================
#  Entry point
# ============================================================

def main():
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
