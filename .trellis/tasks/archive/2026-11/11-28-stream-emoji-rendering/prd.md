# 修复含emoji的流式回答重复残留

## Goal

结合用户现有debug日志与代码，定位并修复含VS16 emoji的终端流式回答重复残留，保持原始模型正文、工具执行和机器输出契约。

## Evidence

用户授权直接查看日志并综合代码排查。真实debug.log最新一轮为2026-11-28 13:19:30—13:19:44，仅有generation/watcher生命周期；generation.end位于finally，不能据此排除渲染或上游问题。独立假provider验证正常增量未自行复制；独立grapheme终端模型重放真实Rich14.0.0输出，首句只输入/返回一次，却在60/200列与6/12行视口均留下108次。原因是☀️/❤️按终端两列而Rich只计一列，行尾padding引发额外自动换行，光标回退不足。

上游官方Rich #3897/#3930及14.3.0发布确认VS16问题；14.3.3同时修正split_graphemes无限循环。当前声明rich>=13.9.4，锁为14.0.0。选择现有Rich的修复版本，不新增依赖或配置，不对模型内容去重。

## Feature examples

TTY终端（emoji按两列显示，60或200列）在一次工具调用和流式回答完成后只保留一次正文，工具输出不被重放：

~~~text
Assistant:
@Function call: get_weather({"city":"Hangzhou","language":"zh"})
[既有工具结果区域]
今天杭州天气不错，是个晴天 ☀️

当前天气：晴，17°C。
~~~

以上方括号仅表示既有工具区域，不是新增提示。成功退出码保持0；TTY保留Rich格式。非TTY/JSON/NDJSON的stdout、stderr、事件、最终内容和退出码不变。纯文本、中文、普通emoji与工具确认、取消和查看器流程保留原语义。

## Scope

提高现有Rich最低版本至已核实修复版本，定向更新uv.lock并补真正经过Printer/Live的独立显示宽度断言。不要改provider协议，不做内容去重，不删emoji，不加应用层Unicode表或全局monkeypatch，不扩大debug日志收集范围。本轮确认的是可复现的同类终端渲染缺陷，不冒充已连接并实测用户的终端。

## Acceptance criteria

- E1 新回归在原Rich14.0.0上先失败；唯一输入/最终正文仍为一次，失败表现为真实Live帧实际占列超过视口。
- E2 在目标Rich版本上相同回归通过，覆盖☀️、❤️、CJK及普通emoji、60/200列、工具Refresh后续答；使用独立wcwidth而非Rich自身宽度校验。
- E3 实际独立grapheme终端重放由108次残留降至1次，真实工具只执行一次，debug开关前后不改变正文。
- E4 仅定向更新现有依赖，不改变其他package版本；全部相关及完整测试、lint/格式、strict docs、构建和原启动门禁通过。
- E5 独立checker审查，规范记录根因与测试盲点，单独fix提交附加到PR60；最新CI通过后仍须用户明确批准合并，不发布或升版本。
