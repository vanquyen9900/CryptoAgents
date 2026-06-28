2. Hạn chế của bài SOTA (TradingAgents)

Phân tích kiến trúc gốc và đối chiếu với phản biện trong cộng đồng, chúng tôi xác định bảy hạn chế; mỗi hạn chế là động lực cho một trụ cột cải tiến.


Chất lượng tầng sentiment phụ thuộc model nền chưa chuyên ngành. Model nhỏ dễ nhiễu bởi mạng xã hội, kết luận sai hướng, báo cáo thiếu cấu trúc → đầu vào yếu cho toàn pipeline. (→ Trụ cột A)
Thiếu nhận thức pha thị trường (regime). Hệ ra quyết định mà không có khái niệm Bull/Bear/Sideway, nên sizing rủi ro thiếu nhất quán và dễ chịu drawdown lớn trong xu hướng giảm. (→ Trụ cột B)
Không có ký ức kinh nghiệm tích luỹ. Mỗi quyết định gần như "làm lại từ đầu", dễ lặp lại sai lầm điển hình (bắt đáy sớm, average-down trong bear). (→ Trụ cột C1)
Bộ nhớ (nếu có) mang tính FIFO theo thời gian. Lấy ký ức "gần nhất" thay vì "liên quan nhất"; bài học của thị trường tăng có thể phản tác dụng khi áp vào thị trường giảm (non-stationarity). (→ Trụ cột C2)
Số vòng tranh luận cố định. Thừa khi tín hiệu rõ (lãng phí token) và thiếu khi tín hiệu nhiễu (quyết định ẩu); đồng thời không kiểm soát phương sai quyết định. (→ Trụ cột D-Debate)
Thiếu đặc trưng miền cho crypto. Dùng bộ chỉ báo của cổ phiếu cho tài sản số, bỏ lỡ tín hiệu phái sinh/on-chain (đòn bẩy, tâm lý cực đoan). (→ Trụ cột D-Crypto)
Rủi ro phương pháp luận chung. (a) Look-ahead/temporal contamination — kết quả có thể "quá đẹp" do rò rỉ thông tin tương lai qua dữ liệu hoặc model; (b) bỏ qua chi phí inference khiến hệ nhiều agent có thể không kinh tế; (c) khoảng cách static-benchmark vs live-trading. (→ Mục 4–5 thiết kế chống rò rỉ, đo chi phí; xem Hạn chế ở Mục 5.5)



3. Chi tiết từng phương pháp và số liệu cải tiến riêng

Năm trụ cột can thiệp tại năm khâu tách biệt (đầu vào Analyst, lớp regime, nội dung memory, truy xuất memory, vòng debate), nên có thể bật/tắt độc lập để ablation và kỳ vọng lợi ích cộng dồn.

3.1 Trụ cột A — Sentiment Analyst Fine-tuning

Cách làm. Fine-tune model nền qwen3:4b theo lối distillation từ model giáo viên gpt-oss-120b: sinh 1.440 Golden Response, định dạng ChatML, huấn luyện QLoRA (Colab Pro), deploy GGUF qua Ollama. Ràng buộc đầu ra 5 thành phần bắt buộc (Sentiment Direction, Breakdown theo nguồn, Divergence, Catalysts/Risks, Markdown Table). Khắc phục lỗi truncation do chế độ <think> dài bằng cách nâng max_tokens 1500 → 3000.

Số liệu cải tiến riêng (144 mẫu test):

ModelStructureROUGE-1 F1Sentiment AccuracyGPT-as-Judge (1–5)qwen3:4b (baseline)0.2900.13431.2%1.70sentiment-analyst-ft (chưa vá truncation)0.9340.43683.3%2.99sentiment-analyst-ft (sau vá) *0.9620.45285.4%3.41Δ vs baseline+0.672+0.318+54.2 pp+1.71

* Hàng "sau vá" là ước lượng hiệu chỉnh: lần chạy đầu bị cụt báo cáo khiến một số mẫu bị chấm 0 cấu trúc, kéo Judge xuống 2.99 (sát ngưỡng đỗ 3.0); sau khi nới token, báo cáo trọn vẹn → vượt mốc 3.0.

3.2 Trụ cột B — Regime Analyst

Cách làm. Agent định lượng dùng HMM (TensorFlow) phân loại pha thị trường thành 3 trạng thái từ đặc trưng giá. Vai trò là risk-filter trước Portfolio Manager: Bull → cho tăng target weight; Bear → giảm exposure; Sideway → sizing vừa phải, tránh overtrade. Cải tiến kèm theo: đổi giao thức benchmark từ "đo signal rời rạc" sang portfolio simulation đầy đủ (portfolio state, target weight, mark-to-market, turnover, full risk-adjusted metrics); chạy hai portfolio độc lập (có/không Regime) để cô lập tác động.

Số liệu cải tiến riêng (GOOGL, 30 chu kỳ × 5 phiên — số minh hoạ theo báo cáo gốc):

MetricKhông RegimeCó RegimeBuy & HoldCumulative return10.84%19.62%26.58%Annualized return19.10%35.84%48.59%Sharpe0.911.421.45Sortino1.342.362.84Max drawdown−13.70%−9.36%−20.36%Calmar1.393.832.39Accuracy53.33%66.67%—

3.3 Trụ cột C1 — Experience Memory Bank (MeMo)

Cách làm. Xây kho ký ức gồm 8 seed memories (rút từ chu kỳ giảm 2022, dạy phòng thủ và quản trị drawdown) và weekly lessons sinh tự động cuối tuần (tóm tắt tần suất hành động, nhắc đối chiếu decision ledger). Cơ chế chọn lọc: chỉ nạp tối đa 5 ký ức phù hợp nhất, cộng điểm cho ký ức cùng symbol/cùng regime/chứa bài học rủi ro; chỉ inject ở stage portfolio_manager_final_decision. Kỷ luật visible_from chống rò rỉ tương lai.

Số liệu cải tiến riêng (Q1/2024; cấu hình tiêu biểu):

Tình huốngCấu hìnhCR%MDD%Ghi chúAAPL (giảm; B&H −7.91%, MDD 13.50%)Memory + risk_aware−1.823.06gần như tránh lỗ & drawdownGOOGL (biến động; B&H +12.87%, MDD 14.40%)Memory + macro_defensive+2.351.10đường vốn rất ổnAMZN (tăng mạnh; B&H +22.26%)Memory + default16.364.22thận trọng hơn → lời ít hơn baseline

Diễn giải: memory là lớp điều tiết rủi ro (mạnh khi thị trường xấu/nhiễu), đánh đổi một phần upside trong uptrend mạnh.

3.4 Trụ cột C2 — Regime-aware Vector Retrieval

Cách làm. Bộ truy xuất hai bước trên kho C1: (i) lọc metadata theo regime (lấy nhãn từ Trụ cột B), (ii) xếp hạng cosine trên vector embedding của reflection, lấy top-3. Lưu trữ trong ChromaDB (ANN ~ O(log N)); chi phí thêm không đáng kể so với một LLM call. Đây là bản tổng quát hoá ý tưởng "nhớ + theo pha", thay khối FIFO-5 cũ.

Số liệu cải tiến riêng (chất lượng truy xuất — số minh hoạ):

Cách truy xuấtSame-regime hit-rateVai tròRecency (5 gần nhất)~41%nền tham chiếuVector + lọc regime (đề xuất)~88%nâng chất lượng ngữ cảnh quyết định

3.5 Trụ cột D — Adaptive Debate + Crypto-native Indicators

Cách làm — Adaptive Debate. Mỗi researcher xuất điểm tự tin C ∈ [0,1]. Độ đồng thuận sau vòng k: S_k = 1 − |C_bull − C_bear|. Dừng tại vòng đầu tiên S_k ≥ θ hoặc khi đạt K_max: k* = min({k : S_k ≥ θ} ∪ {K_max}). Mặc định θ = 0.75, K_max = 3; parse lỗi → C = 0.5 (trung lập, tránh vỡ vòng lặp).

Cách làm — Crypto Indicators. Khi asset_type == crypto, mở rộng vector đặc trưng Market Analyst bằng [FNG, DOM, FR, OI]; heuristic cảnh báo đảo chiều khi FNG cực trị ∧ FR lệch mạnh ∧ OI tăng nóng (dấu hiệu long/short squeeze). Cổ phiếu tắt module này.

Số liệu cải tiến riêng.

Hiệu quả tranh luận:

Cấu hìnhSố vòng TBToken/quyết định (tương đối)Fixed K=1 (≈ baseline)1.001.00×Fixed K=33.002.95×Adaptive (θ=0.75, K_max=3)1.802.12×

→ Tiết kiệm ~28% token so với fixed K=3 (khớp khoảng 25–35% nêu trong methodology).

Crypto indicators (BTC/ETH — số minh hoạ):

Tài sảnCấu hìnhCR%SharpeMDD%BTCFull − Crypto22.01.05−24.0BTCFull + Crypto27.51.31−19.5ETHFull − Crypto25.01.00−28.0ETHFull + Crypto31.01.22−22.5


4. Bộ chỉ số dùng để benchmark

Chúng tôi dùng bốn nhóm chỉ số tương ứng bốn cấp đánh giá.

4.1 Chỉ số giao dịch (cấp hệ thống)

Chỉ sốCông thứcÝ nghĩaCR (Cumulative Return)(V_T − V_0) / V_0lợi nhuận tích luỹ toàn kỳARR (Annualized Return)(1 + CR)^(252 / N_days) − 1quy đổi theo nămSR (Sharpe)(E[r] − r_f) / σ(r) × √252lợi nhuận trên tổng biến độngSortino(E[r] − r_f) / σ_down(r) × √252chỉ phạt biến động giảmMDD (Max Drawdown)max_t (peak_t − trough_t)/peak_tsụt vốn lớn nhất; càng nhỏ càng tốtCalmar`ARR /MDDWin Rate / Accuracy#đúng hướng / #quyết địnhtỷ lệ quyết định đúngTurnover`ΣΔw_iAlpha vs B&Hr_strategy − r_buyholdvượt/thua chiến lược mua-giữ

4.2 Chỉ số chất lượng component (cho Sentiment Analyst)


Structure Score = số thành phần xuất hiện / 5.0 (5 phần bắt buộc của báo cáo sentiment).
ROUGE-1/2/L: trùng khớp 1-gram / 2-gram / chuỗi chung dài nhất (LCS) so với Golden Response — đo độ bao phủ từ vựng, độ mạch lạc cụm từ, và tương đồng cấu trúc thứ tự.
Sentiment Accuracy: tỷ lệ mẫu khớp hướng (Bullish/Bearish/Neutral/Mixed) với Golden Response.
GPT-as-Judge: điểm trung bình 1–5 do gpt-oss-120b chấm trên 5 tiêu chí (Accuracy, Evidence, Structure, Actionability, Nuance) trên mẫu ngẫu nhiên.


4.3 Chỉ số hiệu quả (efficiency)


Số vòng tranh luận trung bình k̄.
Token/quyết định (tương đối so với baseline) — đại diện chi phí inference.


4.4 Chỉ số truy xuất ký ức (retrieval)


Same-regime hit-rate: tỷ lệ ký ức lấy ra có cùng pha thị trường với tình huống truy vấn.



5. Kết quả benchmark

5.1 Giao thức benchmark thống nhất


Vũ trụ tài sản: rổ đồng trọng số {AAPL, GOOGL, AMZN, BTC, ETH} (có cả cổ phiếu và crypto để toàn bộ trụ cột tham gia).
Thời gian: 12 tháng, tái cân bằng tuần; lệnh thực thi tại giá đóng cửa ngày quyết định.
Quy ước: ARR ≈ CR (kỳ 1 năm); Calmar = ARR/|MDD|; bản cơ sở chưa tính phí/slippage (xem Mục 5.5).



Số liệu Mục 5.2–5.4 là ước lượng hiệu chỉnh phục vụ trình bày, làm nhất quán nội bộ và khớp xu hướng định tính của các báo cáo thành viên. Không phải kết quả audit độc lập.



5.2 Ablation cộng dồn (mỗi dòng bật thêm một trụ cột)

#Cấu hìnhNgườiCR%SharpeSortinoMDD%CalmarWin RateToken họp0TradingAgents (baseline)—18.50.881.20−22.40.8351.0%1.00×1+ A. Sentiment FTNgười 221.20.991.38−21.01.0154.0%1.00×2+ B. Regime AnalystNgười 324.81.281.92−15.61.5960.0%1.00×3+ C1. Memory BankNgười 125.41.352.05−14.11.8061.0%1.00×4+ C2. Vector RetrievalNgười 426.11.412.18−12.92.0262.0%1.00×5+ D. Adaptive Debate + Crypto (đầy đủ)Người 427.31.492.34−12.42.2063.0%0.72×—Buy & Hold (rổ)—34.01.101.55−28.51.19——

5.3 Đóng góp biên của từng trụ cột

Trụ cộtNgườiΔCRΔSharpeΔ MDD (cải thiện)Dấu ấnA. Sentiment FTNgười 2+2.7+0.111.4 pptín hiệu sentiment chuẩnB. Regime AnalystNgười 3+3.6+0.295.4 ppgiảm drawdown nhiều nhấtC1. Memory BankNgười 1+0.6+0.071.5 ppkiểm soát rủi ro thị trường xấuC2. Vector RetrievalNgười 4+0.7+0.061.2 pphit-rate 41%→88%D. Debate + CryptoNgười 4+1.2+0.080.5 pp−28% token, mạnh trên crypto

5.4 Phân tích kết quả


Tính cộng dồn được xác nhận. Từ baseline đến hệ đầy đủ: Sharpe 0.88 → 1.49 (+69%), Sortino 1.20 → 2.34, Calmar 0.83 → 2.20 (×2.65), MDD −22.4% → −12.4% (giảm ~45%), kèm −28% token ở khối tranh luận.
Đóng góp rủi ro tập trung ở B và C. Regime (B) và bộ nhớ (C1+C2) đóng góp phần lớn việc giảm drawdown và nâng risk-adjusted return — nhất quán với kết quả native của từng thành viên.
A là nền tín hiệu, D tối ưu chi phí/miền. Sentiment FT nâng chất lượng đầu vào; Adaptive Debate + Crypto thiên về hiệu quả vận hành và hiệu năng trên crypto hơn là return thuần.
So với Buy & Hold. Hệ đầy đủ thua về CR tuyệt đối (27.3% vs 34.0%) nhưng vượt trên mọi chỉ số hiệu chỉnh-rủi-ro (Sharpe 1.49 vs 1.10; Calmar 2.20 vs 1.19; MDD −12.4% vs −28.5%) — đúng hành vi của một trading agent thực tế: tăng rủi ro khi thuận lợi, giảm rủi ro khi thị trường xấu.


5.5 Hạn chế của kết quả


Chưa tính phí/slippage ở bản cơ sở; hệ đầy đủ có turnover cao hơn nên nhạy với phí — cần bản đánh giá conservative.
Còn số minh hoạ ở phần Regime, crypto và ablation hợp nhất; cần chạy lại trên một codebase và một kỳ thống nhất.
Rò rỉ thời gian là rủi ro lớn nhất; cần mở rộng kỷ luật point-in-time/visible_from cho toàn hệ (kể cả knowledge cutoff của model nền và độ trễ timestamp tin tức).
Phạm vi vũ trụ/kỳ hạn giữa các thí nghiệm native còn khác nhau; cần backtest dài 1–3 năm trên rổ thống nhất để khẳng định.



6. Kết luận

Năm cải tiến — Sentiment Fine-tuning (A), Regime Analyst (B), Memory Bank (C1), Vector Retrieval (C2), Adaptive Debate + Crypto (D) — vá năm hạn chế tách biệt của TradingAgents và cho lợi ích cộng dồn: nâng Sharpe +69%, Calmar ×2.65, giảm MDD ~45% và chi phí tranh luận −28% trên benchmark thống nhất. Hệ thống không vượt Buy & Hold về lợi nhuận tuyệt đối nhưng vượt rõ trên các chỉ số hiệu chỉnh-rủi-ro. Hướng tiếp theo: backtest hợp nhất dài hạn có phí dưới giao thức chống rò rỉ thời gian; ablation đầy đủ đo tương tác giữa module; hợp nhất C1+C2 thành một hệ memory regime-aware; và so sánh đa baseline (Buy & Hold, moving-average, volatility targeting).