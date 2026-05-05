**花錢:**
0. 訂閱gemini pro獲得新的google帳號: https://premlogin.com/esh8Nu0T  去找折扣碼5% 永豐幣倍卡美金結帳 
1. 用新的google帳號訂閱claude pro: https://premlogin.com/ 。 https://claude.ai/acquired 永豐幣倍卡美金結帳
(2. chatgpt plus: r06帳號)
3. 免費訂閱zeabur pro: https://zeabur.com/zh-TW/pricing?utm_source=banner&utm_medium=landing&utm_campaign=pricing-2026-04 + Aliyun shenzen 5USD/mo 14天以內要取消。記得要先截圖19+5
購買新的伺服器3美元singapore?
4. openrouter一次儲值剩餘的金額:(包含平台手續費)
https://openrouter.ai/settings/credits  永豐幣倍卡


**安裝 skills:**
1. https://github.com/langchain-ai/langchain-skills
2. https://github.com/langchain-ai/langsmith-skills
3. https://github.com/alirezarezvani/claude-skills/tree/main/engineering-team (npx ai-agent-skills install alirezarezvani/claude-skills/engineering-team)
4. https://github.com/alirezarezvani/claude-skills/tree/main/engineering-team/playwright-pro (claude plugin install pw@claude-skills)
5. https://github.com/alirezarezvani/claude-skills/tree/main/engineering (npx ai-agent-skills install alirezarezvani/claude-skills/engineering)
6. https://github.com/lackeyjb/playwright-skill
(# Add this repository as a marketplace
/plugin marketplace add lackeyjb/playwright-skill

# Install the plugin
/plugin install playwright-skill@playwright-skill

# Navigate to the skill directory and run setup
cd ~/.claude/plugins/marketplaces/playwright-skill/skills/playwright-skill
npm run setup)

(7. https://github.com/lefterisloukas/edgar-crawler / https://github.com/NataliaZarina/sec-10k-downloader / https://edgartools.readthedocs.io/en/latest/installation/)

8. https://github.com/OctagonAI/skills/tree/main/skills/sec-10k-analysis / 
9. https://github.com/zeabur/agent-skills


**下prompt**:
你是一位萬能什麼都會的end-to-end full stack AI/LLM/Agent Engineer (最擅長python、langchain ecosystem)，現在你收到了一份測驗，裡面包含三項tasks需要你完成，相關的細節說明請參考 @progress_notes.md (包含: @_JobDescription.md 、 @_TaskDescription.md、 @_ThoughtsDraft.md等等) 。
 @progress_notes.md這會是我與妳共同維護的文件，當你確認完成一個項目就記得將checkbox打x，並且要附上你的相關證明與附註說明、意見/建議於底下，你也可以用這份文件來撰寫你的疑問或困難或是目前開發進度、還欠缺什麼沒落地、接下來的todos等等，或用來跟我進行雙向溝通/說明/確認tasks實作方向或是其他開發細節、更新進度等等。
 最後請生成具有意義的commit command文字內容給我參考，我來自己下指令commit push。



 因為notes/briefs/底下會有敏感性的資料，因此請務必記得要將 notes/briefs/ 資料夾底下的所有檔案都要加入到.gitignore 中 notes/_briefs/。


 本來原始的todos寫在 @notes/thoughts/implementation_plan-1.md


接碼商: https://5sim.net/zh/manual / https://play.google.com/store/apps/details?id=sms.message.safe.sim.safesim&hl=zh_TW / https://www.binance.com/zh-TC/square/post/29545003154826 


請先徹底了解目前repo的所有進度、實作與狀況等等( 撰寫於 @notes/thoughts/ 中的 implementation_plan-*.md 、 task-*.md 、 walkthrough-*.md 當中 )，包含了解 @notes/_briefs/_TaskDescription.md 目標與需求，以及 @notes/thoughts/_ThoughtsDraft.md 中的一些想法概念參考(僅做為提供初步思維)。 另外 @notes/progress/progress_notes.md 會是我與你共同維護的文件，當你確認完成一個項目就記得將checkbox打x，如果有其他建議的代辦事項也會需要你進行列點補充，並且要附上你的相關證明與附註說明、意見/建議於底下，你也可以用這份文件來撰寫你的疑問或困難或是目前開發進度、還欠缺什麼沒落地、接下來的todos等等，或用來跟我進行雙向溝通/說明/確認tasks實作方向或是其他開發細節、更新進度、筆記待完成事項、紀錄思考做法等等。 你也有相當多的skills 於 @.agents/ @.claude/ 可以參考可以怎麼加入相關best practice於repo當中，以讓開發更加robust且更可以考慮到各種edge cases。
需要你思考看看目前的 @AGENTS.md 與 @CLAUDE.md 是否有需要加強或是優化修改的地方，並且也請檢閱 @notes/progress/architecture_design_spec.md 看看可以怎麼加強，以及 @README.md 可以怎麼來寫跟補強(凸顯超過面試官預期有多做多思考的機制跟演算法等等)。 同時你也需要去檢閱根據 @notes/progress/progress_notes.md 與對應 @notes/_briefs/_TaskDescription.md @notes/thoughts/_ThoughtsDraft.md 思考看看目前的實作(包含所有phases與tasks)還有哪些需要再補強跟優化。 
除了上述事項需要優化強化以外，接下來你也同步會需要繼續完成實作Phase 3 Task 1繼續根據目前repo現況來落地執行開發看可以如何根據題目一的需求好好地將所有GitHub CI/CD 工作流程封裝為幾個可重用的 Claude Skills。