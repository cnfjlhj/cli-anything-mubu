# mubu-cli

让 AI Agent 直接读写你正在用的幕布笔记。

不是导出工具，不是迁移脚本——是一座桥，把你桌面端打开的幕布文档变成 Agent 可以操作的活数据。

## 它能干什么

你在幕布桌面端写笔记，`mubu-cli` 让 Codex / Claude Code 这样的 AI Agent 同时做这些事：

```
浏览文档          搜索内容          定位节点
    │                │                │
    └──── 全部基于本地数据，不碰线上 API ────┘
                     │
                     v
            选中目标节点后
                     │
         ┌───────────┼───────────┐
         v           v           v
      追加子节点    修改文本    删除节点
         │           │           │
         └── 走线上 API，但默认 dry-run ──┘
                     │
                     v
              确认无误后 --execute
```

读操作走本地备份，快且安全。写操作走线上 API，但**默认只预览不执行**——你得显式加 `--execute` 才会真正改动。

## 为什么不直接用 API

幕布没有公开的开发者 API。

`mubu-cli` 的做法是：读操作走桌面端本地存储（备份文件、RxDB 元数据、同步日志），写操作复用桌面端的认证会话调用内部接口。不需要额外登录，不需要 token——只要幕布桌面端开着就行。

## 安全模型

这是整个项目最重要的设计决策：

| 规则 | 原因 |
|------|------|
| 写操作默认 dry-run | 看到完整 payload 再决定要不要执行 |
| 执行后自动回读验证 | 不靠返回值，靠实际重新拉取确认 |
| 删除走整棵子树 | 删父节点会连带所有子节点，CLI 会明确提示 |
| 不做批量写入 | 一次改一个节点，保持操作原子性 |

## 快速上手

```bash
# 克隆
git clone https://github.com/cnfjlhj/cli-anything-mubu.git
cd cli-anything-mubu

# 安装
python3 -m venv .venv
.venv/bin/python -m pip install -e .

# 确认幕布桌面端正在运行，然后：
.venv/bin/mubu-cli
```

无参数启动进入 REPL，可以交互式浏览和操作。

## 命令一览

四个域，职责清晰：

```
mubu-cli
├── discover    浏览：文档列表、文件夹、每日笔记
├── inspect     查看：全文搜索、节点树、同步记录
├── mutate      改动：追加子节点、修改文本、删除节点
└── session     状态：记住当前文档/节点，跨次复用
```

常用路径：

```bash
# 找到今天的每日笔记
mubu-cli discover daily-current --json

# 看里面的节点结构
mubu-cli inspect daily-nodes --query '待办' --json

# 在某个节点下追加一行（先预览）
mubu-cli mutate create-child --parent-node-id abc123 --text '新任务' --json

# 确认没问题，执行
mubu-cli mutate create-child --parent-node-id abc123 --text '新任务' --execute --json
```

## REPL

无参数启动进入 REPL，支持：

- `use-doc` / `use-node` 选中当前操作目标
- 选中状态跨会话持久化
- `@doc` / `@node` 占位符自动展开
- 命令历史记录

```
$ mubu-cli
mubu> use-doc 'Workspace/Daily tasks/26.03.24'
mubu> use-node abc123
mubu> status
```

## 架构

```
              幕布桌面端
             /         \
     本地存储            线上 API
    (备份/RxDB/日志)    (需桌面端认证会话)
         |                   |
     读/浏览/搜索       查看节点 + 写操作
         \                   /
          \                 /
           mubu-cli 统一入口
                |
          Codex / Claude Code / 你
```

两个平面：

- **读平面**：走本地文件，覆盖面广，不触网
- **写平面**：走线上 API，范围窄，dry-run 优先

## 适用场景

- 让 Agent 帮你整理每日笔记
- 在编程会话中直接更新幕布里的任务清单
- 用脚本批量读取幕布文档内容做分析
- 把幕布当作 Agent 工作流的数据源

## 不适合什么

- 批量迁移或导出（这不是导出工具）
- 没装幕布桌面端的机器（依赖本地存储）
- 需要多人协作 API 的场景（这是单用户桥接）

## CLI-Anything 兼容

本项目遵循 [CLI-Anything](https://github.com/HKUDS/CLI-Anything) 的 harness 规范：

- 标准的 Click 分组命令结构
- `cli-anything-mubu` 兼容入口
- 内置 SKILL.md 供 Agent 自动发现

上游 PR：[CLI-Anything#99](https://github.com/HKUDS/CLI-Anything/pull/99)

## 环境要求

- Python 3.8+
- 幕布桌面端正在运行（Windows / WSL 均可）
- 桌面端数据默认在 `AppData/Roaming/Mubu/` 下，自动发现

可通过环境变量覆盖路径，详见源码中的 `MUBU_BACKUP_ROOT` 等配置项。

## License

MIT
