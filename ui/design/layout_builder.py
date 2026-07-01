"""Main design-mode layout builders."""

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from node_editor import NodeCanvasScene, NodeCanvasView
from operator_registry import NODE_REGISTRY
from ui.design.config_pages import make_empty_config_page
from ui.design.toolbox import ToolboxWidget


def build_dock_workspace(owner):
    owner.dock_main = QMainWindow()
    owner.dock_main.setStyleSheet(
        "QMainWindow::separator { width: 3px; height: 3px; background: #D8DEE6; }"
        "QMainWindow::separator:hover { background: #AEB8C2; }"
        "QDockWidget { titlebar-close-icon: none; titlebar-normal-icon: none; }"
        "QDockWidget::title { text-align: left; padding: 4px 8px; "
        "background: #F8FAFC; border-bottom: 1px solid #DCE3EA; "
        "font-size: 12px; font-weight: 600; color: #1F2933; }"
    )
    owner.dock_main.setDockNestingEnabled(True)
    owner.dock_main.setTabPosition(
        Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea,
        QTabWidget.North,
    )

    _build_canvas(owner)
    _build_toolbox_dock(owner)
    _build_preview_dock(owner)
    owner._all_docks = [owner.dock_toolbox, owner.dock_preview]
    return owner.dock_main


def _build_canvas(owner):
    canvas_container = QWidget()
    canvas_layout = QVBoxLayout(canvas_container)
    canvas_layout.setContentsMargins(0, 0, 0, 0)
    canvas_layout.setSpacing(0)

    owner.canvas_scene = NodeCanvasScene()
    owner.canvas_scene.node_selected.connect(owner.on_canvas_node_selected)
    owner.canvas_scene.node_double_clicked.connect(owner.on_canvas_node_double_clicked)
    owner.canvas_scene.right_clicked.connect(owner.show_context_menu)
    owner.canvas_scene.edge_changed.connect(owner._on_edge_changed)

    owner.canvas_view = NodeCanvasView(owner.canvas_scene)
    owner.canvas_view.copy_requested = owner.copy_selected_nodes
    canvas_layout.addWidget(owner.canvas_view)
    QTimer.singleShot(0, owner.canvas_view.center_on_canvas)

    owner.dock_main.setCentralWidget(canvas_container)


def _build_toolbox_dock(owner):
    owner.toolbox = ToolboxWidget()
    owner.toolbox.add_node_requested.connect(owner.add_node_to_canvas)
    owner.dock_toolbox = QDockWidget("工具箱")
    owner.dock_toolbox.setObjectName("dock_toolbox")
    owner.dock_toolbox.setWidget(owner.toolbox)
    owner.dock_toolbox.setFeatures(
        QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
    )
    owner.dock_toolbox.topLevelChanged.connect(
        lambda floating, dock=owner.dock_toolbox: owner._on_dock_float_changed(dock, floating)
    )
    owner.dock_main.addDockWidget(Qt.LeftDockWidgetArea, owner.dock_toolbox)


def _build_preview_dock(owner):
    right_panel = QWidget()
    right_layout = QVBoxLayout(right_panel)
    right_layout.setContentsMargins(0, 0, 0, 0)
    right_layout.setSpacing(4)

    preview_header = QHBoxLayout()
    owner.chk_auto_follow = QCheckBox("自动跟随")
    owner.chk_auto_follow.setChecked(True)
    owner.chk_auto_follow.setStyleSheet("font-weight: bold; color: #2196F3;")
    owner.chk_auto_follow.stateChanged.connect(owner._on_auto_follow_changed)

    owner.combo_preview_tables = QComboBox()
    owner.combo_preview_tables.setMinimumWidth(120)
    owner.combo_preview_tables.addItem("暂无数据")
    owner.combo_preview_tables.setStyleSheet("""
        QComboBox { background: white; border: 1px solid #ccc; border-radius: 3px; padding: 2px 5px; color: black; }
        QComboBox QAbstractItemView { background-color: white; color: black; selection-background-color: #E1F5FE; }
    """)
    owner.combo_preview_tables.currentIndexChanged.connect(owner._on_manual_combo_changed)

    owner.preview_title = QLabel("未选择")
    owner.preview_title.setStyleSheet("color: #888;")
    owner.lbl_shape = QLabel("")

    preview_header.addWidget(owner.chk_auto_follow)
    preview_header.addWidget(owner.combo_preview_tables)
    preview_header.addWidget(owner.preview_title, stretch=1)
    preview_header.addWidget(owner.lbl_shape)

    owner.preview_tabs = QTabWidget()
    owner.preview_tabs.setStyleSheet("""
        QTabWidget::pane { border: 1px solid #eee; background: white; }
        QTabBar::tab { background: #f5f5f5; border: 1px solid #ddd; padding: 4px 10px;
            border-top-left-radius: 3px; border-top-right-radius: 3px; margin-right: 1px; font-size: 11px; }
        QTabBar::tab:selected { background: #E1F5FE; color: #0277BD; border-bottom: none; }
    """)
    owner.preview_tabs.currentChanged.connect(owner._on_tab_changed)

    right_layout.addLayout(preview_header)
    right_layout.addWidget(owner.preview_tabs)

    owner.dock_preview = QDockWidget("数据预览")
    owner.dock_preview.setObjectName("dock_preview")
    owner.dock_preview.setWidget(right_panel)
    owner.dock_preview.setMinimumHeight(180)
    owner.dock_preview.setFeatures(
        QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
    )
    owner.dock_preview.topLevelChanged.connect(
        lambda floating, dock=owner.dock_preview: owner._on_dock_float_changed(dock, floating)
    )
    owner.dock_main.addDockWidget(Qt.BottomDockWidgetArea, owner.dock_preview)


def build_config_dialog(owner):
    owner.dock_config = QDockWidget("算子配置")
    owner.dock_config.setObjectName("dock_config")
    owner.dock_config.setMinimumWidth(320)
    owner.dock_config.setAllowedAreas(Qt.RightDockWidgetArea)
    owner.dock_config.setFeatures(QDockWidget.DockWidgetMovable)
    owner.config_dialog = owner.dock_config

    config_container = QWidget()
    config_container.setStyleSheet("""
        QWidget { background: #F3F6FA; }
        QStackedWidget { background: #F3F6FA; border: none; }
    """)
    config_layout = QVBoxLayout(config_container)
    config_layout.setContentsMargins(0, 0, 0, 0)
    config_layout.setSpacing(0)

    owner.config_area = QStackedWidget()
    owner.panel_instances = {}

    for action, config in NODE_REGISTRY.items():
        panel = config["panel_class"](owner.ctx.data_pool)
        panel.set_runtime_parameters(owner.runtime_parameters, owner.parameter_mappings)
        if hasattr(panel, "set_global_code"):
            panel.set_global_code(getattr(owner, "global_code", ""))
        if hasattr(panel, "global_code_changed"):
            panel.global_code_changed.connect(owner.on_global_code_changed)
        if hasattr(panel, "code_editor_saved"):
            panel.code_editor_saved.connect(owner.on_code_editor_saved)
        if hasattr(panel, "code_editor_run_requested"):
            panel.code_editor_run_requested.connect(owner.on_code_editor_run_requested)
        panel.save_requested.connect(owner.on_tool_saved)
        panel.run_requested.connect(owner.on_tool_run_requested)
        owner.config_area.addWidget(panel)
        owner.panel_instances[action] = panel

    owner.panel_empty = make_empty_config_page()
    owner.config_area.addWidget(owner.panel_empty)
    owner.panel_instances["sys_empty"] = owner.panel_empty

    owner.config_area.setCurrentWidget(owner.panel_empty)
    config_layout.addWidget(owner.config_area)
    owner.dock_config.setWidget(config_container)
    owner.dock_main.addDockWidget(Qt.RightDockWidgetArea, owner.dock_config)
    owner._all_docks = [owner.dock_toolbox, owner.dock_config, owner.dock_preview]

    QTimer.singleShot(
        0,
        lambda: owner.dock_main.resizeDocks(
            [owner.dock_toolbox, owner.dock_config], [240, 360], Qt.Horizontal
        ),
    )
    QTimer.singleShot(
        0,
        lambda: owner.dock_main.resizeDocks([owner.dock_preview], [220], Qt.Vertical),
    )
    return owner.dock_config
