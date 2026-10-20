<!-- SPDX-FileCopyrightText: 2026 Imperial Auto Governor contributors -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# 安全政策

OGAS 使用 GitHub 内置私密漏洞报告：
[Report a vulnerability](https://github.com/V2t-Nostalgia/OGAS/security/advisories/new)。
该渠道已启用；报告不会成为公开 issue。不要自行公开可利用细节，等待维护者协调披露。

请不要在公开 issue 中粘贴 API 密钥、上传令牌、前端密码、完整存档、抓包、局域网拓扑或个人路径。
私密报告也应只附必要的最小复现，优先说明源码 commit、具体位置、影响与脱敏证据。
大型受限资料按研究归档访问状态单独协商，不把凭据写入源码或公开档案。

支持范围以当前发布分支为准。房主桥必须以管理员权限运行 WinDivert，但 LLM API、网页控制台和存档解析不应以管理员身份运行。控制台绑定非回环地址时必须启用 TLS 和认证。

网页检索结果是不可信输入。任何网页文本均不得覆盖系统提示、本地候选引擎、对象标识、执行确认或网络改写安全条件。
