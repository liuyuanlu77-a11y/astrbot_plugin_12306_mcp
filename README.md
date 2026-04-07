<div align="center">

![:name](https://count.getloli.com/@astrobot_plugin_12306_mcp?name=astrobot_plugin_12306_mcp&theme=minecraft&padding=6&offset=0&align=top&scale=1&pixelated=1&darkmode=auto)

# astrbot_plugin_12306_mcp

## 🚄 12306 火车票助手（MCP + 车站大屏）_本工具基于大语言模型开发（新手开发，请多指教）

[![License](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![AstrBot](https://img.shields.io/badge/AstrBot-4.17%2B-orange.svg)](https://github.com/Soulter/AstrBot)
[![GitHub](https://img.shields.io/badge/作者-rong--dai-blue)](https://github.com/yourname)

</div>

---

## 🤝 插件介绍

`astrobot_plugin_12306_mcp` 是一个对接 **12306 MCP 服务器** + **NathanAPI 车站大屏** 的火车票查询插件，提供官方余票、车次、时刻表、中转换乘、车站实时大屏等功能，并支持大模型自动调用。

核心特性：

- 🚆 **12306 官方查询**：余票、车次、票价、时刻表、中转换乘、车站搜索等（通过 MCP 协议）
- 🚉 **车站大屏**：实时查询指定车站出发/到达列车信息（车次、终到站、发车/到达时间、检票口、状态等）
- 🤖 **大模型自动调用**：提供 `call_12306_mcp`、`get_station_board`、`query_train_detail` 三个 LLM Tool，自然语言即可触发
- 📄 **长文本文件发送**：当车站大屏返回超过 20 趟列车时，自动生成 `.txt` 文件发送，避免刷屏
- 🔍 **列车详情定位**：查询指定车次时，自动从车站大屏中匹配该车次实时信息，并整合网络新闻
- ⚙️ **WebUI 配置**：支持修改 MCP 连接地址、NathanAPI Key、超时时间等，无需手动改代码

---

## 📦 安装

### 方式一：插件市场（推荐）
在 AstrBot WebUI 的插件市场中搜索 **12306 MCP 查询助手**，点击安装并启用。

### 方式二：手动安装
将插件文件夹放入 `AstrBot/data/plugins/` 目录，重启 AstrBot 即可。

---

## ⚙️ 配置说明

请前往 **AstrBot WebUI → 插件管理 → 12306 MCP 查询助手 → 配置** 进行设置。

### 🔌 MCP 连接配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `mcp_connection.type` | 连接类型：`streamable_http`（推荐）、`sse`、`stdio` | `streamable_http` |
| `mcp_connection.sse_url` | MCP 服务器地址（Streamable HTTP 或 SSE） | `http://localhost:8000/mcp` |
| `mcp_connection.timeout` | 查询超时（秒） | `30` |
| `mcp_connection.auto_reconnect` | 自动重连 MCP 服务器 | `true` |
| `mcp_connection.excluded_tools` | 禁止注册到 LLM 的工具名列表（如 `["ping"]`） | `[]` |

> 如果你使用 Docker 部署 12306 MCP 服务器，且 AstrBot 也在 Docker 中，请将 `sse_url` 改为 `http://12306-mcp-server:8000/mcp`（容器名称）或 `http://host.docker.internal:8000/mcp`（同一宿主机）。

### 📡 车站大屏配置（NathanAPI）

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `nathan_api.api_key` | NathanAPI 平台 API Key（**必填**） | 空 |
| `nathan_api.timeout` | 请求超时时间（秒） | `15` |

> 获取 API Key：[https://api.nanyinet.com](https://api.nanyinet.com) → 注册 → 开通“12306车站大屏”接口。

### 🧩 LLM 集成设置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `llm_integration.auto_register_tools` | 自动注册 LLM 工具 | `true` |

---

## ⌨️ 使用说明

### 一、自然语言对话（推荐）

大模型会自动识别意图并调用相应工具，你只需像平常聊天一样询问即可。

| 你想问的问题 | 大模型调用的工具 |
|--------------|------------------|
| “查一下明天北京到上海的高铁余票” | `call_12306_mcp` |
| “北京站现在出发的列车有哪些” | `get_station_board` |
| “C6928 次列车从广州南出发的实时信息” | `query_train_detail` |

### 二、手动命令

| 命令 | 说明 | 示例 |
|------|------|------|
| `/12306` 或 `/12306帮助` | 显示帮助信息 | `/12306` |
| `/12306_tools` | 查看 MCP 服务器提供的所有工具 | `/12306_tools` |
| `/12306_call <工具名> <JSON参数>` | 直接调用 MCP 工具 | `/12306_call query-tickets '{"from":"北京","to":"上海","date":"2026-04-07"}'` |
| `/station_board <车站名> [depart\|arrive]` | 查询车站大屏（出发/到达） | `/station_board 广州南`<br>`/station_board 上海虹桥 arrive` |
| `/train_detail <车次> [出发站] [到达站] [日期]` | 查询车次详情（经停站+大屏定位） | `/train_detail C6928 广州南` |

### 三、LLM 工具列表（供大模型自动调用）

插件自动注册以下三个工具，大模型可根据描述自主选择使用：

1. **`call_12306_mcp`**  
   调用 MCP 服务器上的任意工具（余票、车站搜索、中转换乘、经停站、当前时间等）。

2. **`get_station_board`**  
   查询车站实时大屏信息（出发/到达列车列表）。

3. **`query_train_detail`**  
   查询指定车次的经停站信息，并自动从车站大屏中定位该车次的实时动态，同时可整合网络新闻。

---

## 🐳 部署 12306 MCP 服务器（Docker）项目地址：https://github.com/drfccv/mcp-server-12306

本插件本身不包含 MCP 服务器，你需要单独运行以下容器（也可以选择其他方式部署，不会可以问AI）：

```bash
docker pull drfccv/12306-mcp-server:latest
docker run -d -p 8000:8000 --name 12306-mcp-server drfccv/12306-mcp-server:latest
  ```

确保 AstrBot 容器能够访问该地址（网络模式需互通）localhost最好改成服务器地址

## 📌 注意事项
- NathanAPI Key 必须配置，否则车站大屏功能无法使用。

- 自然语言调用可能受大模型偏好影响，若大模型执意使用网络搜索而非本插件工具，可尝试在提示词中明确要求使用插件工具。

- /12306_reload 命令已移除（因会导致 AstrBot 重启），如需重连 MCP 服务器，请通过 WebUI 重载插件或重启容器。

- 车站大屏数据来源于第三方接口，实际信息请以车站现场公告为准。

## 🤝 贡献与反馈（在此鸣谢drfccv和NathanAPI提供的服务）
- 🌟 Star 这个项目！（点右上角的星星，感谢支持！）
- 🔧 你也可以改进代码使用

## 📄 开源协议
- 本项目采用 MIT License 开源。

## ⚠️ 免责声明
- 本项目仅供学习、研究与技术交流，严禁用于任何商业用途。
- 本项目不存储、不篡改、不传播任何 12306 官方数据，仅作为官方公开接口的智能聚合与转发。
- 使用本项目造成的任何后果（包括但不限于账号封禁、数据异常、法律风险等）均由使用者本人承担，项目作者不承担任何责任。
- 请遵守中国法律法规及 12306 官方相关规定，合理合规使用。

## 欢迎加入AstrBot 开发
- QQ 群 975206796（AstrBot 官方开发者群）
- 作者联系邮箱：liului_1456@163.com（不一定有空看）






