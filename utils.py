from PyQt5.QtCore import QPointF, QLineF
from PyQt5.QtGui import QPainterPath, QPolygonF, QPen, QBrush, QColor, QPainter


def bezier_edge_path(start_point, end_point):
    """构建贝塞尔曲线路径（源节点右侧 → 目标节点左侧）"""
    path = QPainterPath()
    path.moveTo(start_point)

    dist = min(max(abs(end_point.x() - start_point.x()) * 0.4, 60), 200)
    ctrl1 = QPointF(start_point.x() + dist, start_point.y())
    ctrl2 = QPointF(end_point.x() - dist, end_point.y())
    path.cubicTo(ctrl1, ctrl2, end_point)

    return path


def arrow_polygon(end_point, size=10):
    """构建指向 end_point 的左向箭头三角形"""
    return QPolygonF([
        end_point,
        end_point + QPointF(-size, -size / 2),
        end_point + QPointF(-size, size / 2),
    ])


def draw_grid_background(painter, rect, grid_size=20):
    """在 painter 上绘制网格背景"""
    painter.fillRect(rect, QColor("#f0f2f5"))

    left = int(rect.left()) - (int(rect.left()) % grid_size)
    top = int(rect.top()) - (int(rect.top()) % grid_size)

    lines = []
    x = left
    while x < rect.right():
        lines.append(QLineF(x, rect.top(), x, rect.bottom()))
        x += grid_size
    y = top
    while y < rect.bottom():
        lines.append(QLineF(rect.left(), y, rect.right(), y))
        y += grid_size

    pen = QPen(QColor("#e0e4e8"), 1)
    painter.setPen(pen)
    painter.drawLines(lines)


def topological_layout(items, get_outgoing, get_sort_key, set_pos_func,
                       x_spacing=320, y_spacing=140, start_x=100, start_y=200):
    """对 items 进行拓扑分层自动布局，通过 set_pos_func(item, x, y) 设置位置"""
    if not items:
        return

    # 1. 构建无向邻接表（用于连通分量检测）
    undirected_adj = {n: [] for n in items}
    for n in items:
        for dest in get_outgoing(n):
            undirected_adj[n].append(dest)
            if dest in undirected_adj:
                undirected_adj[dest].append(n)

    # 2. 求连通分量
    visited = set()
    components = []
    for n in items:
        if n not in visited:
            comp = []
            q = [n]
            visited.add(n)
            while q:
                curr = q.pop(0)
                comp.append(curr)
                for neighbor in undirected_adj[curr]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        q.append(neighbor)
            components.append(comp)

    current_base_y = start_y

    for comp_nodes in components:
        # 4. 拓扑排序分配层级
        in_degree = {n: 0 for n in comp_nodes}
        adj_list = {n: [] for n in comp_nodes}
        for n in comp_nodes:
            for dest in get_outgoing(n):
                if dest in in_degree:
                    adj_list[n].append(dest)
                    in_degree[dest] += 1

        queue = [n for n in comp_nodes if in_degree[n] == 0]
        layer_map = {n: 0 for n in queue}

        while queue:
            curr = queue.pop(0)
            for neighbor in adj_list[curr]:
                layer_map[neighbor] = max(layer_map.get(neighbor, 0), layer_map[curr] + 1)
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # 5. 按层分组 & 组内排序
        layers = {}
        for n in comp_nodes:
            l = layer_map.get(n, 0)
            if l not in layers:
                layers[l] = []
            layers[l].append(n)

        for l in layers:
            layers[l].sort(key=get_sort_key)

        max_nodes_in_layer = max(len(lst) for lst in layers.values()) if layers else 1
        comp_height = (max_nodes_in_layer - 1) * y_spacing
        comp_center_y = current_base_y + comp_height / 2

        for l_idx in sorted(layers.keys()):
            layer_nodes = layers[l_idx]
            num_nodes = len(layer_nodes)
            layer_height = (num_nodes - 1) * y_spacing
            node_start_y = comp_center_y - layer_height / 2
            stagger_offset = (y_spacing * 0.5) if (l_idx % 2 != 0) else 0

            for i, node in enumerate(layer_nodes):
                x = start_x + l_idx * x_spacing
                y = node_start_y + i * y_spacing + stagger_offset
                set_pos_func(node, x, y)

        current_base_y += comp_height + y_spacing * 2.0
