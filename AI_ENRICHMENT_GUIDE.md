# CineVault Studio — Root CLI AI Model Metadata & Tag Enrichment Guide (`AI_ENRICHMENT_GUIDE.md`)

> **Target Audience**: CLI-mode AI Models (Claude Code, Gemini CLI, OpenAI Codex CLI, Aider, Cursor Agent) and Human Operators.

## 1. 核心规则与证据匹配优先级 (Strict Rules & Evidence Priority)

1. **证据匹配顺序（严格按此优先级）**：
   `文件名日期 (file_name date) > 系列目录 (parent_dirs series/studio) > 女优目录 (parent_dirs actress) > 用户备注 (user_keywords) > 视频时长 (duration_sec) > 现有标题 (title)`
   - **警惕错误合集标题**：库里已有的 `title` 很可能是合集名（例如 `Club VXN` 多支单场文件被存成合集名）或本地正则切分残片。
   - **用 `duration_sec` 区分单场与合集**：单场（Scene）时长通常在 `1200s ~ 3600s`（20~60 分钟），整部合集（Compilation / Full Movie）通常 `> 5400s`（90 分钟以上）。若 `duration_sec` 显示为单场时长，**严禁沿用合集标题**，必须用 `文件名日期 + 系列 + 演员 + 时长` 匹配对应的单场标题与标签。

2. **系列/厂牌 → 必有标签对照表（Series → Mandatory Tags Table）**：
   只要文件名、目录或厂牌命中以下系列，**必须**包含对应标签（无需猜测）：
   | 系列 / 厂牌 / 目录名 | 必有标签 (Mandatory Tags) |
   | :--- | :--- |
   | `Lubed` | `Oil` |
   | `Tushy`, `Tushy Raw`, `All Anal`, `True Anal`, `AnalVids` | `Anal` |
   | `Blacked`, `Blacked Raw`, `BBC Pie`, `Monsters Of Cock`, `Dogfart Network` | `Interracial` |
   | `Hogtied` | `Bondage`, `BDSM` |
   | `Sex and Submission`, `Dungeon Sex` | `BDSM` |
   | `Anal Oil Latex`（系列目录/合集名） | `Anal`, `Oil`, `Latex` |
   | `Oil Overload`（系列目录/合集名） | `Oil` |
   | `Squirt Explosion`（系列目录/合集名） | `Squirt` |
   | `Swallowed`, `Throated`, `Blowpass` | `Blowjob`, `Deepthroat` |
   | `Love Her Feet` | `Feet` |
   | `Fantasy Massage` | `Massage` |
   | `Lesbea` | `Lesbian` |

3. **标签词表限制与“对不上就留空”原则（No Guessing & No Prompting User Item-by-Item）**：
   - **只允许使用库里已有的标准标签词表**（见下方第 2 节完整词表）。
   - 用 `日期 + 系列 + 演员 + 时长` 去对场次：**确切对上场次才写具体行为标签**；若对不上具体场次且文件名无明确行为词，则 `tags` **保持 `[]`（或仅保留上表中的系列必有标签）**，并在该条 JSON 记录中填写 `"tag_note": "未匹配到具体场次，仅保留系列标签/留空"`。
   - **严禁向用户逐条提问确认，严禁猜测，严禁把 `Hardcore` 或 `Blowjob` 默认贴到每一支硬戏上！**

4. **年龄合规政策（Age Policy: 18+ Standard）**：
   - 本库收录的商业成人作品均以法定 **18 周岁（18+）** 为唯一成年合规判定基准（遵循 18 U.S.C. § 2257 商业厂牌合规存档）。
   - 凡拍摄时年满 18 周岁的商业厂牌演员，请正常补全完整元数据与性行为分类标签，**严禁按 21 岁（under-21）标准拦截或清空已有标签**。
   - 仅当某条记录被明确标记为未满约定年龄（18 岁）时，不写性行为标签。

5. **厂牌别名登记红线（Series & Platform Blocklist）**：
   - **`Anal Oil Latex`、`Oil Overload`、`Squirt Explosion` 是系列/合集名，不是厂牌！**
   - **`Pornhub`、`Pron Hub`、`PH-*`、`OnlyFans`、`ManyVids`、`XVideos` 是视频平台或上传者前缀，不要登记成厂牌！**
   - 严禁将上述系列名或平台名写入 `studio` 或 `new_studio_alias_to_register`。

6. **标签合并与校对模式（Tag Merge & `tags_only` Mode）**：
   - 导入时系统会自动将非空 `tags` 与库里已有标签合并，**空数组 `[]` 绝不会覆盖库里已有标签**。
   - 若 `AI_KEYWORD_DB.md` 顶部标注当前为 **`export_mode: tags_only`（标签专项校对模式）**，则**本轮只允许修改 `tags` 和 `tag_note`**，请勿改动 `studio`、`title`、`performers`、`release_date`。

---

## 2. 库内允许使用的标准类型标签词表 (Allowed Genre Tags Vocabulary)

请严格从以下标准词表中选用 `tags`（区分大小写规范展示）：

- **玩法与体裁 (Acts & Fetish)**:
  `Anal`, `Oil`, `Latex`, `BDSM`, `Bondage`, `Femdom`, `Fetish`, `Feet`, `Blowjob`, `Deepthroat`, `Handjob`, `Titfuck`, `Creampie`, `Cumshot`, `Facial`, `Swallow`, `Squirt`, `DP`, `Fisting`, `Gape`, `Ass To Mouth`, `Rimming`, `Rough`, `Hardcore`, `Softcore`, `Romantic`, `Massage`, `Cuckold`, `Cheating`
- **人数与组合 (Group & Orientation)**:
  `Threesome`, `Foursome`, `Gangbang`, `Orgy`, `Lesbian`, `Interracial`, `BBC`, `Solo`, `Masturbation`, `Striptease`
- **服饰与道具 (Costume & Toys)**:
  `Lingerie`, `Stockings`, `Pantyhose`, `Fishnet`, `High Heels`, `Uniform`, `Maid`, `Nurse`, `Secretary`, `Teacher`, `Cosplay`, `Toys`, `Dildo`, `Vibrator`, `Machine`
- **外貌特征与角色 (Attributes & Archetypes)**:
  `MILF`, `Mature`, `Teen`, `Blonde`, `Brunette`, `Redhead`, `Asian`, `Latina`, `Ebony`, `Busty`, `Big Ass`, `Natural Tits`, `Petite`, `Tattoo`, `Piercing`
- **场景与视角 (Setting & Format)**:
  `POV`, `VR`, `Glamour`, `Public`, `Outdoor`, `Pool`, `Shower`, `Office`, `Gym`, `Casting`, `Amateur`, `Parody`
- **日系/字幕特定标签 (JAV & Subtitles)**:
  `中文字幕`, `无码破解`, `FC2 素人`

---

## 3. 就地编辑工作流 (Mode B: In-Place File Editing Workflow)

1. 在 CineVault Studio 界面点击 **「✨ AI 补全与新厂牌收录」**，选择：
   - **导出模式 1（默认）**：导出未完成元数据记录到 `AI_KEYWORD_DB.md`（每批 25 条）。
   - **导出模式 2（标签专项校对 `tags_only`）**：只导出标签为空或系列标签缺失的记录到 `AI_KEYWORD_DB.md`（每批 25 条，本轮只改 `tags` 与 `tag_note`）。
2. 让 CLI 模型直接就地读取并修改 `AI_KEYWORD_DB.md` 中的 JSON 数组并保存文件。
3. 回到软件点击 **「⚡ 导入 AI 补全结果」**（无需复制粘贴，软件会自动读取磁盘上的 `AI_KEYWORD_DB.md` 并安全合并标签）。
