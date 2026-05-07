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


please run the task 2 eval and verify the Zeabur live deploy at signal-foundry.zeabur.app/health
並且也請仔細檢查 @notes/progress/progress_notes.md line 1 ~ 128 去驗證是否真的所有相關todo checklist都已經完成，如果完成的請幫我[x]，如果還沒的請羅列出來以後並且開始完成所有實做與加強優化。 你可以搭配 @notes/_briefs/_TaskDescription.md 與 @notes/thoughts/_ThoughtsDraft.md 來強化增強整個系統，以能夠解決更多的edge cases，並將更多的corner cases真實案例那到eval set當中。
(目前的系統狀況summary寫在 @notes/thoughts/ 中的  walkthrough-*.md 當中 提供給你初步參考目前有完成的內容。)


please push and verify zeabur deployed the new fixes and all tasks work smoothly ; also confirm Zeabur finishes deploying the pushed commit
請再次檢查所有已經[x]的todo checklist與tasks細節是否真的都已經有完成完畢了，並且幫我實際真的去跑通所有的tasks而不再只是停留在smoke run/test，而是真的能work能花錢能去跑出完美結果的給reviewer
請不斷迭代進行explore與實際使用每個tasks，並且持續發掘潛在問題，然後修復遇到的問題與issues/corner cases。以更能夠解決所有real world可能遇到的complex edge cases。
並且幫我修復所有的edge cases,提升調用LLM的能力(花錢沒關係)並持續改善優化prompt， 讓每個tasks題目都可以擴增更加增強解決更多的corner cases

please continue, 並且持續實驗迭代LLM prompt與使用結合整合方式，以讓所有的題目可以變得更加robust且能夠cover更多的edge cases
其中測試跑動時候，優先預設使用免費的NVIDIA_API_KEY例如moonshotai/kimi-k2.6 ；而如果要使用測試openrouter則預設模型使用google/gemini-3.1-pro-preview來做為付費或fallback替代方案做測試。 而實際上在使用demo給reviewers時，reviewer需要提供輸入使用他們自己的key，並且提供模型選項讓他們去選擇使用。
除了繼續完成本來的所有任務以外，請也再繼續測試嘗試其他更廣泛的use cases並且不斷迭代系統來讓tasks可以處理得更妥當與強大
並且也請持續關注zeabur deploy看看是否一切都有正常如預期

please continue請先繼續完成上述原本原先的所有事情。並且不斷迭代優化測試系統直到可以把所有的tasks的corner cases都可以覆蓋解決完整，並且有完善的fallback recover機制避免系統有問題或是中斷hang住。除了繼續完成本來的所有任務以外，請也再繼續測試嘗試其他更廣泛的use cases並且不斷迭代系統來讓tasks可以處理得更妥當與強大，並且也請持續關注zeabur deploy看看是否一切都有正常如預期。
全部這些都完成以後，另外我也於 @notes/progress/progress_notes.md 新增撰寫了 Phase 6 的需求，請也繼續全部都完成實作好來。然後再進行全部檢查所有已經[x]的todo checklist與tasks細節是否真的都已經有完成完畢了，並且幫我實際真的去跑通所有的tasks而不再只是停留在smoke run/test，而是真的能work能花錢能去跑出完美結果的給reviewer。請不斷迭代進行explore與實際使用每個tasks，並且持續發掘潛在問題，然後修復遇到的問題與issues/corner cases。以更能夠解決所有real world可能遇到的complex edge cases。並且幫我修復所有的bugs與edge cases,提升調用LLM的能力(花錢沒關係)並持續改善優化prompt與強化LLM模組functions，讓每個tasks題目都可以擴增更加增強解決更多的corner cases。

please continue請先繼續完成上述原本原先的所有事情。 
請先確保task 2 與task 3 的流程當中也都已經會可以結合use_vision的功能，讓使用者可以決定是否要自動多代入所有相關screenshots給到llm去做輔助判斷，請確保系統已經自代有snapshot模組可以自動將所有得到拍照的截圖都能夠截取出來並且附加給LLM。並且再繼續思考擴充更多task 3和task 2的cases，以能夠找到可以發揮use_vision=true表現才會比較好的案例。也請在仔細思考看看langsmith還有什麼好用實用值得用適合用可以搭配近來的好功能可以一併整合開發到系統當中，提升langsmith observability、evaluation等等的使用/功能/追蹤/metrics/versioning/engineering豐富度。
接下來請思考目前的zeabur deploy網頁 https://signal-foundry.zeabur.app/ 還有哪些值得去做更進一步改善優化的事情，提升視覺化效果；然後再去完成所有新的Phase 7需求，以能夠讓reviewer更容易去操作執行每個tasks看到input output和操作運作流程跟結果。


please continue iterating on edge cases
請確保use_vision於task 2可以有助於LLM去理解網頁中的圖片解答問題，並且可以透過多張系統操作當前狀態的screenshots來增進網站操作的可靠度與成功機率；請思考看看還可以怎麼強化use_vision的benefit來讓task 2 LLM可以更強大並且處理更多不同種的網站類型操作。
並且也請確保use_vision於task 3 可以真的使用完整的多個snapshots去幫助parsing模組，然後對於格式變異極大如HTML不統一、標題寫法多元、舊格式是純文字、Part III 常「incorporated by reference」指向 Proxy、部分 item 為 Not Applicable 或 Reserved等等的情境都可以提升更強的準確度與robustness輸出結構化 JSON，每個 item 包含 `part`、`item_number`、`item_title`、`content_text`、`char_range`、`status`（`extracted` / `incorporated_by_reference` / `not_applicable` / `reserved`）。請仔細思考看看該怎麼設計snapshot/screenshot模組來幫助task 3的LLM以利可以協助解決各種刁鑽格式的處理與parsing得到更加完美的結果。
然後再請繼續完成所有Phase 7的優化與改進。

please continue請先繼續完成上述原本原先的所有事情。 確保use_vision於task 2可以有助於LLM去理解網頁中的圖片解答問題，並且可以透過多張系統操作當前狀態的screenshots來增進網站操作的可靠度與成功機率；請思考看看還可以怎麼強化use_vision的benefit來讓task 2 LLM可以更強大並且處理更多不同種的網站類型操作。
並且也請確保use_vision於task 3 可以真的使用完整的多個snapshots去幫助parsing模組，然後對於格式變異極大如HTML不統一、標題寫法多元、舊格式是純文字、Part III 常「incorporated by reference」指向 Proxy、部分 item 為 Not Applicable 或 Reserved等等的情境都可以提升更強的準確度與robustness輸出結構化 JSON，每個 item 包含 `part`、`item_number`、`item_title`、`content_text`、`char_range`、`status`（`extracted` / `incorporated_by_reference` / `not_applicable` / `reserved`）。請仔細思考看看該怎麼設計snapshot/screenshot模組來幫助task 3的LLM以利可以協助解決各種刁鑽格式的處理與parsing得到更加完美的結果。
然後再請繼續完成所有Phase 7的優化與改進。
然後請再徹底仔細思考看看task 1、task 2、task 3的LLM所有相關模組/prompts/tools/function calling可以再延伸擴展強化的地方強化的地方? 請持續iterate不同的edge cases看看LLM function還可以怎麼強化優化，並且增加可以提升可靠度的功能features，讓reviewers使用者用起來可以更加得心應手好用。並且也思考網站視覺化呈現還可以再怎麼改進強化，使操作起來更流暢更加易懂明瞭且資訊豐富，提升UIUX。


6. [] Phase 6 全系統完整徹底強化與延展優化
  1. [] 確保task 1 已經可以順利透過利用本repo 以及 我自己公開的另一個repo https://github.com/tychen5/Medical-Summary-Builder 來於zeabur deploy網址上來去做到完成的live demo給reviwer徹底檢查。
  2. [] 擴增題目二eval set的更多台灣相關金融相關知名網站與使用scenarios，並確保task 2之eval set 能夠涵蓋不同 domain（e-commerce、banking、news、Google、複雜 SPA）、task type（form fill、scrape、multi-step navigation）、edge cases（CAPTCHA 提示、login wall、JS heavy site、mobile view）。至少 20-30 cases，分 success/partial/fail + 人工驗證 ground truth。且涵蓋多個不同維度例如： Domain diversity-電商/金融/新聞/政府網站； Task complexity-單步/多步/需要 login/需要等待 async response； Failure injection-故意注入 selector 不穩定、網路延遲、CAPTCHA；Edge cases-SPA 路由、iframe 嵌套、shadow DOM、動態載入 等等
  3. [] 擴充題目三的不同實際格式eval set(不同HTML、不同標體寫法、不同新舊格式或純文字、不同Proxy指向、不同item applicable/reserved等)，並確保task 3 之eval set 已經有涵蓋舊格式、incorporated、非標題化案例等等 並且有刻意挑 edge cases 橫跨不同產業（至少包含tech、finance、energy）、年份（舊 vs 新）、公司規模、格式（HTML 變異、純文本、tables heavy、incorporated cases等等. eval set edge case 設計至少需要包括： 1993 年以前的純文字 filing（極舊格式）； Part III 大量 incorporated by reference 的 filing； 超大型公司（蘋果、微軟）vs 小型微型公司； 外國私人發行人的 20-F（格式完全不同）； 破產申報、特殊目的公司、涵蓋不同產業、年份、公司規模，包含一些舊格式 等等
    4. [] 確保已經有在zeabur部署好API了，並且於README當中去撰寫reviewer應該要怎麼去呼叫它來輸入不同的filings得到結果。需要你於README中詳細撰寫調用的方式、schema、input output、parameters、output examples等等。
    5. [] 並確保README已經有報告相關的準確度、失敗模式、以及成本/延遲
  6. [] 比較並記錄7個不同模型於eval set的cost、latency、performance等不同維度面向matrix的分數與表現，並且分析問題與限制所在，尤其是至少需要包含task 2 task 3 的比較紀錄。然後task 2與task 3 的LLM也全都要是multi-modality的(請確保這兩個tasks的所有七個moodel調用vision附上screenshot的使用與輸入方式模組，以及是否都可以支持use_vision toggle)，也就是這些vision-language model要能夠支援可以輸入當前的snapshot給LLM去輔助輔佐判斷下一步動作或是該如何更精準正確的萃取所需資訊出來。
    7. [] 根據上述得到的eval report來反思，需要再額外強化workflow、優化pipeline、或是新增哪些模組、修改prompt、開發新functions、調整哪些參數配置等等，才能夠讓系統更加robust，解決更多更廣的use cases
    8. [] 將系統結合langsmith，以能夠擴展延伸相關observability、比較不同version evaluation結果、透過UI console可以查閱合適metrics、提供有用有助益的traces紀錄、得知trace requests、 瞭解完整evaluate outputs、 儲存不同test prompts、prompt engineering、versioning等等。 你可以利用 @.agents/skills 中的合適skills或上網搜尋相關的best practices來協助你思考該怎麼鄭和開發。
  9. [] 確保所有的tasks題目都已經順利可以於zeabur deploy的網址去操作給reviewer來使用測驗了，所有的tasks都要可以真正支援且正常去live demo使用於real world complex use cases。
    10. [] reviewer需要於zeabur調用tasks時提供nvidia或是openrouter的api key才可以開放使用llm involved的流程機制功能，否則只能使用基本款會有諸多限制且performance比較差。這些題目都應該要更多involve圍繞於LLM的極致發揮與應用才對，請務必讓所有的tasks都可以好好善用解放LLM的實力與優勢。
  11. [] **Zeabur live deploy**: 推到 main 之後 Zeabur 會 auto-deploy。Public URL `https://signal-foundry.zeabur.app` 已在 README、AGENTS.md 中引用。手動 sanity check `/health`、`/api/v1/models` 兩個 endpoint 即可。
  12. [] **Task 2 live eval run**: 需要穩定的網路 + Playwright headless Chromium + LLM budget (約 $0.30 一輪)。runner (`evals/task2/run_eval.py`) 已就位，可隨時執行並把報告 commit 進 `evals/task2/results/`。

from openai import OpenAI
import os
import sys

_USE_COLOR = sys.stdout.isatty() and os.getenv("NO_COLOR") is None
_REASONING_COLOR = "\033[90m" if _USE_COLOR else ""
_RESET_COLOR = "\033[0m" if _USE_COLOR else ""

client = OpenAI(
  base_url = "https://integrate.api.nvidia.com/v1",
  api_key = "$NVIDIA_API_KEY"
)


completion = client.chat.completions.create(
  model="z-ai/glm-5.1",
  messages=[{"role":"user","content":""}],
  temperature=1,
  top_p=1,
  max_tokens=16384,
  extra_body={"chat_template_kwargs":{"enable_thinking":True,"clear_thinking":False}},
  stream=True
)

for chunk in completion:
  if not getattr(chunk, "choices", None):
    continue
  if len(chunk.choices) == 0 or getattr(chunk.choices[0], "delta", None) is None:
    continue
  delta = chunk.choices[0].delta
  reasoning = getattr(delta, "reasoning_content", None)
  if reasoning:
    print(f"{_REASONING_COLOR}{reasoning}{_RESET_COLOR}", end="")
  if getattr(delta, "content", None) is not None:
    print(delta.content, end="")
  

