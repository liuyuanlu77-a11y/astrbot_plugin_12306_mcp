import asyncio
import json
import tempfile
import os
import re
from datetime import datetime
from typing import Dict, Any, List, Optional

import httpx
from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star
from astrbot.api.message_components import File

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.streamable_http import streamablehttp_client


class MCP12306Plugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.mcp_session: Optional[ClientSession] = None
        self.mcp_client = None
        self._connected = False
        self._reconnect_lock = asyncio.Lock()
        self._session_lock = asyncio.Lock()
        self._current_conn_type = None

    # ---------- MCP 连接管理 ----------
    async def _connect_streamable_http(self, url: str):
        try:
            self.mcp_client = streamablehttp_client(url)
            read, write, _ = await self.mcp_client.__aenter__()
            session = ClientSession(read, write)
            await session.__aenter__()
            await session.initialize()
            self.mcp_session = session
            self._connected = True
            self._current_conn_type = "streamable_http"
            logger.info(f"[12306MCP] ✅ Streamable HTTP 连接成功: {url}")
        except Exception as e:
            logger.error(f"[12306MCP] ❌ Streamable HTTP 连接失败: {e}")
            raise

    async def _connect_sse(self, url: str):
        self.mcp_client = sse_client(url)
        read, write = await self.mcp_client.__aenter__()
        session = ClientSession(read, write)
        await session.__aenter__()
        await session.initialize()
        self.mcp_session = session
        self._connected = True
        self._current_conn_type = "sse"
        logger.info(f"[12306MCP] ✅ SSE 连接成功: {url}")

    async def _connect_stdio(self, command: str, args: List[str]):
        server_params = StdioServerParameters(command=command, args=args)
        self.mcp_client = stdio_client(server_params)
        read, write = await self.mcp_client.__aenter__()
        session = ClientSession(read, write)
        await session.__aenter__()
        await session.initialize()
        self.mcp_session = session
        self._connected = True
        self._current_conn_type = "stdio"
        logger.info(f"[12306MCP] ✅ stdio 连接成功: {command} {' '.join(args)}")

    async def connect_mcp(self):
        conn_cfg = self.config.get("mcp_connection", {})
        conn_type = conn_cfg.get("type", "streamable_http")
        try:
            if conn_type == "streamable_http":
                url = conn_cfg.get("sse_url", "http://localhost:8000/mcp")
                await self._connect_streamable_http(url)
            elif conn_type == "sse":
                url = conn_cfg.get("sse_url", "http://localhost:8000/sse")
                await self._connect_sse(url)
            elif conn_type == "stdio":
                command = conn_cfg.get("stdio_command", "python")
                args = conn_cfg.get("stdio_args", ["-m", "mcp_server_12306"])
                await self._connect_stdio(command, args)
            else:
                raise ValueError(f"未知连接类型: {conn_type}")
        except Exception as e:
            logger.error(f"[12306MCP] ❌ 连接失败: {e}")
            self._connected = False
            raise

    async def disconnect_mcp(self):
        async with self._session_lock:
            if self.mcp_session:
                try:
                    await self.mcp_session.__aexit__(None, None, None)
                except:
                    pass
                self.mcp_session = None
            self._connected = False
            logger.info("[12306MCP] MCP 会话已关闭")

    async def ensure_connected(self):
        if self._connected and self.mcp_session:
            return
        if not self.config.get("mcp_connection", {}).get("auto_reconnect", True):
            raise ConnectionError("MCP 未连接且自动重连已禁用")
        async with self._reconnect_lock:
            if self._connected and self.mcp_session:
                return
            logger.warning("[12306MCP] 尝试自动重连...")
            await self.disconnect_mcp()
            await self.connect_mcp()

    async def call_mcp_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        await self.ensure_connected()
        timeout = self.config.get("mcp_connection", {}).get("timeout", 30)
        try:
            async with asyncio.timeout(timeout):
                result = await self.mcp_session.call_tool(tool_name, arguments=arguments)
                texts = [c.text for c in result.content if hasattr(c, "text")]
                return "\n".join(texts) if texts else "（无返回内容）"
        except asyncio.TimeoutError:
            return f"⏰ 调用 {tool_name} 超时（{timeout}秒）"
        except Exception as e:
            logger.error(f"[12306MCP] 工具调用失败: {e}")
            return f"❌ 调用失败: {str(e)}"

    # ---------- 车站大屏业务逻辑 ----------
    async def query_station_board(self, station_name: str, query_type: str = "depart") -> tuple[str, bool]:
        nathan_config = self.config.get("nathan_api", {})
        api_key = nathan_config.get("api_key", "")
        if not api_key:
            return "❌ NathanAPI Key 未配置，请在 WebUI 中设置", False

        timeout = nathan_config.get("timeout", 15)
        api_url = "https://api.nanyinet.com/api/gateway/12306/api.php"
        params = {"apikey": api_key, "stationName": station_name}

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(api_url, params=params)
                data = response.json()

            if data.get("code") != 1:
                return f"❌ API 错误: {data.get('msg', '未知错误')}", False

            result_data = data.get("data", {})
            if query_type == "depart":
                screens = result_data.get("departure", {}).get("stationWaitingScreens", [])
                if not screens:
                    return f"未查询到 {station_name} 站的出发列车信息", False
                lines = [f"🚉 {station_name}站 出发列车实时信息"]
                for train in screens:
                    line = (f"🚆 {train.get('trainNo', '未知')}次 | "
                            f"终到: {train.get('endStationName', '')} | "
                            f"发车: {train.get('departTime', '')} | "
                            f"状态: {train.get('waitingState', '')} | "
                            f"检票口: {train.get('wicket', '')}")
                    lines.append(line)
                if len(screens) > 20:
                    lines.append(f"\n📊 共 {len(screens)} 趟列车，完整列表已生成文件")
                    full_text = "\n".join(lines)
                    return full_text, True
                else:
                    return "\n".join(lines), False
            else:
                screens = result_data.get("arrival", {}).get("stationArrivalScreens", [])
                if not screens:
                    return f"未查询到 {station_name} 站的到达列车信息", False
                lines = [f"🚉 {station_name}站 到达列车实时信息"]
                for train in screens:
                    line = (f"🚆 {train.get('trainNo', '未知')}次 | "
                            f"始发: {train.get('startStationName', '')} | "
                            f"到达: {train.get('arrivalTime', '')} | "
                            f"状态: {train.get('arrivalState', '')} | "
                            f"出站口: {train.get('exitingPort', '')}")
                    lines.append(line)
                if len(screens) > 20:
                    full_text = "\n".join(lines)
                    return full_text, True
                else:
                    return "\n".join(lines), False

        except httpx.TimeoutException:
            return f"⏰ 请求超时（{timeout}秒）", False
        except Exception as e:
            logger.error(f"[12306MCP] 车站大屏查询失败: {e}")
            return f"❌ 查询失败: {str(e)}", False

    # ---------- LLM 工具 ----------
    @filter.llm_tool(name="call_12306_mcp")
    async def tool_call_mcp(self, event: AstrMessageEvent, tool_name: str, arguments: str) -> str:
        """
        调用 12306 MCP 服务器上的工具。
        Args:
            tool_name(string): MCP 工具名称，如 query-tickets, search-stations, query-transfer, get-train-route-stations, get-current-time 等
            arguments(string): JSON 格式的参数字符串
        """
        try:
            args_dict = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError as e:
            return f"参数 JSON 解析失败: {e}"
        result = await self.call_mcp_tool(tool_name, args_dict)
        return result

    @filter.llm_tool(name="get_station_board")
    async def tool_station_board(self, event: AstrMessageEvent, station_name: str, type: str = "depart") -> str:
        """
        【必须使用】查询指定车站的实时列车到发信息（车站大屏）。
        当用户询问某个火车站的实时列车信息（如“北京站现在出发的列车”、“上海虹桥站到达列车时刻表”、“车站大屏”、“实时车次”等）时，必须使用此工具，而不是进行网络搜索。
        Args:
            station_name(string): 车站名称，如“北京”、“上海虹桥”
            type(string): 查询类型，可选 depart（出发列车）或 arrive（到达列车），默认为 depart
        """
        text, need_file = await self.query_station_board(station_name, type)
        if need_file:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
                f.write(text)
                tmp_path = f.name
            # 在工具中发送文件（不能 yield，只能 await event.send）
            await event.send(MessageChain().file(tmp_path, filename=f"{station_name}_车站大屏.txt"))
            os.unlink(tmp_path)
            return f"已将 {station_name} 站{ '出发' if type=='depart' else '到达' }列车完整列表以文件形式发送，请查收。"
        else:
            return text

    @filter.llm_tool(name="query_train_detail")
    async def tool_train_detail(self, event: AstrMessageEvent, train_no: str, from_station: str = "", to_station: str = "", date: str = "") -> str:
        """
        查询指定车次的详细信息（经停站、时刻、正晚点等），并自动从车站大屏中定位该车次，整合相关网络新闻。
        适用于用户询问某个具体列车的实时动态（如“C6928次列车现在到哪里了？”）。
        Args:
            train_no(string): 车次号，如 C6928, G1
            from_station(string): 出发站（可选，用于精确定位）
            to_station(string): 到达站（可选）
            date(string): 日期，格式 YYYY-MM-DD，默认为今天
        """
        if not date:
            # 获取当前日期
            time_resp = await self.call_mcp_tool("get-current-time", {})
            match = re.search(r'(\d{4}-\d{2}-\d{2})', time_resp)
            if match:
                date = match.group(1)
            else:
                date = datetime.now().strftime("%Y-%m-%d")

        result_parts = []
        if from_station:
            board_text, _ = await self.query_station_board(from_station, "depart")
            lines = board_text.split('\n')
            train_line = None
            for line in lines:
                if train_no in line:
                    train_line = line
                    break
            if train_line:
                result_parts.append(f"【{from_station}站大屏实时信息】\n{train_line}")
            else:
                result_parts.append(f"⚠️ 在 {from_station} 站未找到车次 {train_no} 的实时信息，可能列车已发出或不在该站停靠。")

        # 通过 MCP 获取经停站信息
        route_info = await self.call_mcp_tool("get-train-route-stations", {"train_no": train_no, "date": date})
        if route_info.startswith("❌"):
            result_parts.append(f"经停站查询失败：{route_info}")
        else:
            result_parts.append(f"【经停站信息】\n{route_info}")

        # 网络搜索新闻（如果配置了 Tavily Key）
        tavily_key = self.config.get("tavily_api_key", "")
        if tavily_key:
            search_query = f"{train_no}次列车 正晚点 新闻"
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post("https://api.tavily.com/search", json={
                        "api_key": tavily_key,
                        "query": search_query,
                        "max_results": 3
                    })
                    if resp.status_code == 200:
                        search_data = resp.json()
                        news_items = [f"• {r['title']}: {r['snippet']}" for r in search_data.get('results', [])]
                        if news_items:
                            result_parts.append("【相关新闻/公告】\n" + "\n".join(news_items))
            except Exception as e:
                logger.warning(f"新闻搜索失败: {e}")

        return "\n\n".join(result_parts)

    # ---------- 生命周期 ----------
    @filter.on_astrbot_loaded()
    async def on_load(self):
        try:
            await self.connect_mcp()
            logger.info("[12306MCP] 插件初始化完成，LLM 工具已自动注册（call_12306_mcp, get_station_board, query_train_detail）")
        except Exception as e:
            logger.error(f"[12306MCP] 初始化失败，请检查配置: {e}")

    async def unload(self):
        await self.disconnect_mcp()

    # ---------- 手动命令 ----------
    @filter.command("12306", alias={"12306帮助"})
    async def cmd_help(self, event: AstrMessageEvent):
        yield event.plain_result(
            "🚄 12306 火车票助手（含车站大屏、列车详情）\n"
            "大模型会自动调用以下工具：\n"
            "• call_12306_mcp - 余票/车站/中转/经停站查询\n"
            "• get_station_board - 车站大屏实时信息\n"
            "• query_train_detail - 指定车次详情（经停站+实时定位+新闻）\n"
            "手动命令：\n"
            "/12306_tools   - 查看 MCP 服务器提供的所有工具\n"
            "/12306_call <工具名> <JSON参数> - 直接调用 MCP 工具\n"
            "/station_board <车站名> [depart|arrive] - 查询车站大屏\n"
            "/train_detail <车次> [出发站] [到达站] [日期] - 查询车次详情\n"
            "配置修改请在 WebUI 中进行。"
        )

    @filter.command("12306_tools")
    async def cmd_list_tools(self, event: AstrMessageEvent):
        try:
            await self.ensure_connected()
            tools = await self._fetch_mcp_tools()
            lines = ["📦 MCP 服务器提供的工具列表："]
            for t in tools:
                lines.append(f"• {t['name']} - {t['description'][:80]}")
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            yield event.plain_result(f"获取失败: {e}")

    async def _fetch_mcp_tools(self):
        await self.ensure_connected()
        tools_result = await self.mcp_session.list_tools()
        return [{"name": t.name, "description": t.description or ""} for t in tools_result.tools]

    @filter.command("12306_call")
    async def cmd_call_tool(self, event: AstrMessageEvent, tool_name: str = None, json_args: str = None):
        if not tool_name:
            yield event.plain_result("用法: /12306_call <工具名> <JSON参数>")
            return
        if not json_args:
            yield event.plain_result("请提供 JSON 参数，例如: '{\"from\":\"北京\",\"to\":\"上海\",\"date\":\"2026-04-07\"}'")
            return
        try:
            args = json.loads(json_args)
        except json.JSONDecodeError as e:
            yield event.plain_result(f"参数 JSON 解析失败: {e}")
            return

        yield event.plain_result(f"⏳ 调用 {tool_name} ...")
        result = await self.call_mcp_tool(tool_name, args)
        for i in range(0, len(result), 1800):
            yield event.plain_result(result[i:i+1800])

    @filter.command("station_board")
    async def cmd_station_board(self, event: AstrMessageEvent, station_name: str = None, query_type: str = "depart"):
        if not station_name:
            yield event.plain_result("用法: /station_board <车站名> [depart|arrive]\n例如: /station_board 北京 或 /station_board 上海虹桥 arrive")
            return
        text, need_file = await self.query_station_board(station_name, query_type)
        if need_file:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
                f.write(text)
                tmp_path = f.name
            # 使用 MessageChain 发送文件
            yield event.chain_result([File(file=tmp_path, name=f"{station_name}_车站大屏.txt")])
            os.unlink(tmp_path)
        else:
            yield event.plain_result(text)

    @filter.command("train_detail")
    async def cmd_train_detail(self, event: AstrMessageEvent, train_no: str = None, from_station: str = None, to_station: str = None, date: str = None):
        if not train_no:
            yield event.plain_result("用法: /train_detail <车次号> [出发站] [到达站] [日期]\n例如: /train_detail C6928 广州南 佛山西\n如果不提供出发站，将仅查询经停站信息。")
            return
        if not date:
            # 获取当前日期
            time_resp = await self.call_mcp_tool("get-current-time", {})
            match = re.search(r'(\d{4}-\d{2}-\d{2})', time_resp)
            if match:
                date = match.group(1)
            else:
                date = datetime.now().strftime("%Y-%m-%d")

        result_parts = []
        if from_station:
            board_text, _ = await self.query_station_board(from_station, "depart")
            lines = board_text.split('\n')
            train_line = None
            for line in lines:
                if train_no in line:
                    train_line = line
                    break
            if train_line:
                result_parts.append(f"【{from_station}站大屏实时信息】\n{train_line}")
            else:
                result_parts.append(f"⚠️ 在 {from_station} 站未找到车次 {train_no} 的实时信息，可能列车已发出或不在该站停靠。")

        route_info = await self.call_mcp_tool("get-train-route-stations", {"train_no": train_no, "date": date})
        result_parts.append(f"【经停站信息】\n{route_info}")
        yield event.plain_result("\n\n".join(result_parts))