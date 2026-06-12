from collections import deque
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
    """在 painter 上绘制方格背景（小格淡线 + 大格深线）"""
    painter.fillRect(rect, QColor("#fafbfc"))

    left = int(rect.left()) - (int(rect.left()) % grid_size)
    top = int(rect.top()) - (int(rect.top()) % grid_size)

    # 小格线（20px）
    small_lines = []
    x = left
    while x < rect.right():
        small_lines.append(QLineF(x, rect.top(), x, rect.bottom()))
        x += grid_size
    y = top
    while y < rect.bottom():
        small_lines.append(QLineF(rect.left(), y, rect.right(), y))
        y += grid_size

    pen = QPen(QColor("#e8ebed"), 0.5)
    painter.setPen(pen)
    painter.drawLines(small_lines)

    # 大格线（100px，5 小格一条）
    big_size = grid_size * 5
    big_left = int(rect.left()) - (int(rect.left()) % big_size)
    big_top = int(rect.top()) - (int(rect.top()) % big_size)

    big_lines = []
    x = big_left
    while x < rect.right():
        big_lines.append(QLineF(x, rect.top(), x, rect.bottom()))
        x += big_size
    y = big_top
    while y < rect.bottom():
        big_lines.append(QLineF(rect.left(), y, rect.right(), y))
        y += big_size

    pen = QPen(QColor("#d5dbe0"), 1)
    painter.setPen(pen)
    painter.drawLines(big_lines)


def topological_layout(items, get_outgoing, get_sort_key, set_pos_func,
                       x_spacing=320, y_spacing=140, start_x=100, start_y=200,
                       layout_mode="asap"):
    """
    对 items 进行拓扑分层自动布局。

    layout_mode:
      "asap" - 源节点尽量靠左（默认，层级清晰）
      "alap" - 源节点尽量贴近目标（连线短，视觉紧凑）
    """
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
            q = deque([n])
            visited.add(n)
            while q:
                curr = q.popleft()
                comp.append(curr)
                for neighbor in undirected_adj[curr]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        q.append(neighbor)
            components.append(comp)

    current_base_y = start_y

    for comp_nodes in components:
        # 4. 拓扑排序分配层级 (构建正反向邻接表)
        in_degree = {n: 0 for n in comp_nodes}
        adj_list = {n: [] for n in comp_nodes}
        adj_backward = {n: [] for n in comp_nodes}
        for n in comp_nodes:
            for dest in get_outgoing(n):
                if dest in in_degree:
                    adj_list[n].append(dest)
                    adj_backward[dest].append(n)
                    in_degree[dest] += 1

        queue = deque([n for n in comp_nodes if in_degree[n] == 0])
        layer_map = {n: 0 for n in queue}

        while queue:
            curr = queue.popleft()
            for neighbor in adj_list[curr]:
                layer_map[neighbor] = max(layer_map.get(neighbor, 0), layer_map[curr] + 1)
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # ALAP: 源节点贴近目标层，连线更短更紧凑
        if layout_mode == "alap":
            # 从 sink 反向推：每节点尽量贴近其下游
            out_degree = {n: len(adj_list[n]) for n in comp_nodes}
            sinks = [n for n in comp_nodes if out_degree[n] == 0]
            # 保持 sink 在原层（最右列）
            alap_layer = {n: layer_map[n] for n in sinks}
            queue = deque(sinks)
            while queue:
                curr = queue.popleft()
                for src in comp_nodes:
                    if curr in adj_list[src]:
                        out_degree[src] -= 1
                        # src 应紧贴最早的下游
                        candidate = alap_layer[curr] - 1
                        if src not in alap_layer or candidate < alap_layer[src]:
                            alap_layer[src] = candidate
                        if out_degree[src] == 0:
                            queue.append(src)
            # 整体左移使最左为 0
            min_layer = min(alap_layer.values()) if alap_layer else 0
            layer_map = {n: l - min_layer for n, l in alap_layer.items()}

        # 5. 按层分组 & 组内排序
        layers = {}
        for n in comp_nodes:
            l = layer_map.get(n, 0)
            if l not in layers:
                layers[l] = []
            layers[l].append(n)

        for l in layers:
            layers[l].sort(key=get_sort_key)

        # 6. 坐标分配：Y 坐标从前驱继承，保持连线平直
        layer_indices = sorted(layers.keys())
        node_y = {}  # node → y 坐标

        for l_idx in layer_indices:
            layer_nodes = layers[l_idx]
            if l_idx == 0:
                # 第一层：均匀分布
                for i, node in enumerate(layer_nodes):
                    node_y[node] = current_base_y + i * y_spacing
            else:
                # 继承层：每个节点的 Y = 所有前驱 Y 的平均值
                raw = []
                for node in layer_nodes:
                    preds = [p for p in adj_backward.get(node, []) if p in node_y]
                    if preds:
                        node_y[node] = sum(node_y[p] for p in preds) / len(preds)
                    else:
                        node_y[node] = float('inf')  # 无前驱，暂放末尾
                    raw.append(node)
                # 无前驱节点放到当前层最下方
                orphan_y = current_base_y + len(layer_nodes) * y_spacing
                for node in layer_nodes:
                    if node_y[node] == float('inf'):
                        node_y[node] = orphan_y
                        orphan_y += y_spacing
                # 同层去重叠：按 Y 排序后，保底间距推开
                layer_nodes.sort(key=lambda n: node_y[n])
                for i in range(1, len(layer_nodes)):
                    prev_y = node_y[layer_nodes[i - 1]]
                    curr_y = node_y[layer_nodes[i]]
                    if curr_y - prev_y < y_spacing:
                        node_y[layer_nodes[i]] = prev_y + y_spacing

            # 写坐标
            for node in layer_nodes:
                x = start_x + l_idx * x_spacing
                set_pos_func(node, x, node_y[node])

        # 根据实际分配的 Y 推进组件偏移
        all_ys = list(node_y.values())
        current_base_y = max(all_ys) + y_spacing * 2.0 if all_ys else current_base_y
