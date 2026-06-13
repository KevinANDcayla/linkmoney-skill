# LinkMoney - skills.sh 收录指南 (v2 — 修正：无需手动提交)

## 重要：skills.sh 没有 submit 表单

`https://skills.sh/submit` 返回 404。

**skills.sh 是 Vercel Labs 的 Skills Indexer（类似 npmjs.com for skills）**——
它**自动收录**通过 `npx skills add <user/repo>` 安装的 GitHub 仓库，**不需要手动提交**。

平台规模（2026-06）：
- **634,491** skills 收录
- 排名按 install 数（All Time / Trending 24h / Hot 三榜）

## 收录机制

只要以下任一条件满足，仓库就会自动出现在 skills.sh：

1. **有人在本地跑过** `npx skills add KevinANDcayla/linkmoney-skill`
2. 仓库的 `SKILL.md` 包含 frontmatter 且格式合法
3. npx CLI 成功解析并 index

## 怎么让我们出现在 skills.sh（已自动完成）

我们的仓库（https://github.com/KevinANDcayla/linkmoney-skill）已经有合法 `SKILL.md`，
**目前的状态是被动等待首次 `npx skills add` 触发**。

### 加速收录的方法

**方法 A：你亲自跑一次**
```bash
npx skills add KevinANDcayla/linkmoney-skill
```
跑完一次后，skills.sh 的索引器会在 1-24 小时内抓取 + 上线。

**方法 B：让别人跑**（宣传）
在 README、Twitter、Discord、Hacker News 任何地方提到 `npx skills add KevinANDcayla/linkmoney-skill`，
引导开发者自己跑。**install 数 = skills.sh 排名 = 流量**。

**方法 C：让 Vercel 团队收录**
发邮件到 skills@vercel.com，说明：
- Repo: KevinANDcayla/linkmoney-skill
- Description: AI-native B2B marketplace
- Manifest: https://linkmoney.online/mcp/manifest.json
- 申请 "Verified Publisher" 标识

## skills.sh 页面会展示什么

抓 https://www.skills.sh/ 看现有 skill 的展示格式，主要字段：

| 字段 | 值 |
|------|-----|
| Name | linkmoney |
| Owner | KevinANDcayla |
| Repo | KevinANDcayla/linkmoney-skill |
| Description | AI-native B2B marketplace for Chinese factory sourcing |
| Install Command | `npx skills add KevinANDcayla/linkmoney-skill` |
| License | MIT |
| Last Updated | 2026-06 |
| Installs (8W) | 从 0 累计 |

## 优化排名

skills.sh 排名核心是 **8W Activity**（8 周活跃安装数）和 **Total Installs**。

短期（首周目标 100 installs）：
- 在 Anthropic Skills PR 被合并后引导用户从 skills.sh 装
- 抖音/小红书视频描述里挂 `npx skills add ...` 命令
- 给 5-10 个海外 B2B 群里分享

中期（首月目标 1000 installs）：
- 写 "awesome-china-sourcing" 这种 GitHub 列表，把 linkmoney 列进去
- 找 Vercel Labs 申请 "Featured Skill" 标签

## 验证收录

跑过 `npx skills add` 24 小时后，访问：
```
https://www.skills.sh/KevinANDcayla/linkmoney-skill
```
应该能看到 linkmoney 的 skill 详情页。

或者搜：
```
https://www.skills.sh/search?q=linkmoney
```

## 总结：这次不需要主动操作

skills.sh 收录**完全自动**。我们仓库已经合规，**等首次 install 触发**即可。
你的任务是引导用户去跑 `npx skills add` —— 越多人跑，排名越靠前。
