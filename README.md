# 全国展会 Apple 日历订阅（GitHub Pages）

这个仓库会每天自动生成 `docs/china-expos.ics`，用于 Apple/Google/Outlook 的日历订阅。

## 一次性发布步骤（约 5 分钟）

1. 在 GitHub 新建公开仓库（例如：`expo-calendar-subscription`）。
2. 把本目录文件上传到仓库根目录。
3. 在仓库 `Settings -> Pages`：
   - Source 选择 `Deploy from a branch`
   - Branch 选择 `main`，Folder 选 `/docs`
4. 等待 Pages 生效，得到地址：
   - `https://<你的GitHub用户名>.github.io/expo-calendar-subscription/china-expos.ics`
5. 在 GitHub `Actions` 页面，启用工作流（首次可能需要点 `Enable workflows`）。

## 本地先生成一次

```bash
python3 scripts/build_ics.py
```

## Apple 日历订阅

- iPhone：设置 -> 日历 -> 账户 -> 添加账户 -> 其他 -> 添加已订阅的日历
- macOS 日历：文件 -> 新建日历订阅
- 粘贴 ICS 链接并保存。

## 说明

- 数据来源：好展会公开页面（按月计划页聚合）
- 更新频率：每天 1 次（GitHub Actions）
- 时间展示：全天事件
