using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace ArkDeploy {
    internal static class Theme {
        static Dictionary<string, object> Values = Json.Decode(Transport.Resource("theme"));
        public static Color Get(string key) { return ColorTranslator.FromHtml(Json.Text(Values, key)); }
        public static Color Gold = Get("primary"), Text = Get("text"), Muted = Get("muted"), Background = Get("background"), Success = Get("success"), Danger = Get("danger");
    }

    internal sealed class ConsoleForm : Form {
        TextBox host = new TextBox { Text = "acciowork@127.0.0.1" }, root = new TextBox { Text = "D:/commission-system" };
        TextBox port = new TextBox { Text = "2233" }, identityFile = new TextBox { Text = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".ssh/ark_office") };
        Label headline, status, office, cloud, work, stepCount;
        Button inspect, prepare, deploy, resume, export;
        ListView checks, steps;
        RichTextBox plan, log, diagnosis;
        ProgressBar progress;
        TabControl tabs;
        Timer poll;
        bool busy, active, ready, demo;
        string runId = "", preparedId = "", preparedRevision = "", preparedConnection = "";
        Dictionary<string, object> last = new Dictionary<string, object>();
        string stateFile = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "LeShine/DeployConsole/session.json");
        public ConsoleForm(bool demonstration) {
            demo = demonstration;
            Text = "LeShine · 方舟更新中心"; Width = 1220; Height = 900; MinimumSize = new Size(920, 680);
            StartPosition = FormStartPosition.CenterScreen; Font = new Font("Microsoft YaHei UI", 10); BackColor = Theme.Background; ForeColor = Theme.Text;
            AutoScaleMode = AutoScaleMode.Dpi;
            Build();
            if (!demo) LoadSession();
            host.TextChanged += delegate { InvalidatePreparation(); };
            root.TextChanged += delegate { InvalidatePreparation(); };
            port.TextChanged += delegate { InvalidatePreparation(); };
            identityFile.TextChanged += delegate { InvalidatePreparation(); };
            inspect.Click += async delegate { await Inspect(); };
            prepare.Click += async delegate { await StartRelease("prepare"); };
            deploy.Click += async delegate { await StartRelease("deploy"); };
            resume.Click += async delegate { await RefreshRun(true); };
            export.Click += delegate { Export(); };
            poll = new Timer { Interval = 4000 };
            poll.Tick += async delegate { if (active && !busy) await RefreshRun(false); };
            poll.Start();
            FormClosing += delegate(object sender, FormClosingEventArgs args) {
                if ((active || busy) && !demo && MessageBox.Show("办公室任务独立运行，关闭窗口不会取消更新。下次打开后点击「恢复任务」查看同一任务。\n\n关闭客户端？", "任务仍在运行", MessageBoxButtons.YesNo, MessageBoxIcon.Information) != DialogResult.Yes) args.Cancel = true;
            };
            Buttons();
        }
        void Build() {
            var layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(24), ColumnCount = 1, RowCount = 7 };
            foreach (int height in new [] { 74, 106, 98, 52 }) layout.RowStyles.Add(new RowStyle(SizeType.Absolute, height));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 52)); layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 46)); Controls.Add(layout);
            var heading = new Panel { Dock = DockStyle.Fill };
            headline = new Label { Text = "方舟更新中心", Font = new Font(Font.FontFamily, 22, FontStyle.Bold), AutoSize = true, Location = new Point(0, 0) };
            heading.Controls.Add(headline); heading.Controls.Add(new Label { Text = "远程控制办公室统一发布 · 每一步都有结果可查", ForeColor = Theme.Muted, AutoSize = true, Location = new Point(3, 45) }); layout.Controls.Add(heading, 0, 0);
            var connection = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 4, RowCount = 3, BackColor = Color.White, Padding = new Padding(12, 6, 12, 6) };
            connection.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 110)); connection.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 32)); connection.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 130)); connection.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 68));
            connection.Controls.Add(new Label { Text = "办公室 SSH", AutoSize = true, Anchor = AnchorStyles.Left }, 0, 0);
            connection.Controls.Add(host, 1, 0); host.Dock = DockStyle.Fill;
            connection.Controls.Add(new Label { Text = "服务器安装目录", AutoSize = true, Anchor = AnchorStyles.Left }, 2, 0);
            connection.Controls.Add(root, 3, 0); root.Dock = DockStyle.Fill;
            connection.Controls.Add(new Label { Text = "端口（选填）", AutoSize = true, Anchor = AnchorStyles.Left }, 0, 1);
            connection.Controls.Add(port, 1, 1); port.Dock = DockStyle.Fill;
            connection.Controls.Add(new Label { Text = "私钥路径（选填）", AutoSize = true, Anchor = AnchorStyles.Left }, 2, 1);
            connection.Controls.Add(identityFile, 3, 1); identityFile.Dock = DockStyle.Fill;
            var hint = new Label { Text = "直连请填写 用户名@127.0.0.1；端口映射仍需 SSH 账号授权。密钥与主机指纹沿用本机 SSH 配置。", AutoSize = true, ForeColor = Theme.Muted };
            connection.Controls.Add(hint, 0, 2); connection.SetColumnSpan(hint, 4); layout.Controls.Add(connection, 0, 1);
            var cards = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 3, Padding = new Padding(0, 10, 0, 0) };
            for (int i = 0; i < 3; i++) cards.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 33.33f));
            office = Card(cards, 0, "办公室服务器", "本机服务 · 数据库 · 发布前提"); cloud = Card(cards, 1, "leshine.cloud", "北京后端 · 静态站 · 色块服务"); work = Card(cards, 2, "leshine.work", "新加坡静态站 · 隧道 · 关联服务"); layout.Controls.Add(cards, 0, 2);
            var summary = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2 };
            summary.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100)); summary.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 190));
            status = new Label { Text = "从只读自检开始，先确认三处环境是否具备更新条件。", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft };
            stepCount = new Label { Text = "尚未发起任务", Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleRight, ForeColor = Theme.Muted };
            summary.Controls.Add(status, 0, 0); summary.Controls.Add(stepCount, 1, 0); layout.Controls.Add(summary, 0, 3);
            tabs = new TabControl { Dock = DockStyle.Fill, Padding = new Point(18, 8) };
            checks = List(new [] { "环境", "检查项", "状态", "证据 / 下一步" }, new [] { 140, 230, 90, 570 });
            steps = List(new [] { "步骤 / 更新组件", "状态", "说明" }, new [] { 475, 100, 440 });
            plan = TextArea(); log = TextArea(); log.Font = new Font("Consolas", 10); diagnosis = TextArea();
            AddTab("自检结果", checks); AddTab("更新内容", plan); AddTab("更新进度", steps); AddTab("错误诊断", diagnosis); AddTab("运行日志", log); layout.Controls.Add(tabs, 0, 4);
            progress = new ProgressBar { Dock = DockStyle.Top, Height = 5, Style = ProgressBarStyle.Continuous, Margin = new Padding(0, 7, 0, 0) };
            var actions = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.LeftToRight, Padding = new Padding(0, 7, 0, 0), WrapContents = false };
            inspect = ActionButton("1  只读自检", false); prepare = ActionButton("2  准备候选版本", false); deploy = ActionButton("3  确认并更新", true); resume = ActionButton("恢复任务", false); export = ActionButton("导出报告", false);
            actions.Controls.AddRange(new Control[] { inspect, prepare, deploy, resume, export }); layout.Controls.Add(actions, 0, 5);
            var footer = new Panel { Dock = DockStyle.Fill }; footer.Controls.Add(progress);
            footer.Controls.Add(new Label { Text = "准备阶段会获取源码、构建并上传候选制品；确认更新后才切换线上服务。阶段完成数不等于耗时百分比。", AutoSize = true, ForeColor = Theme.Muted, Location = new Point(0, 17) }); layout.Controls.Add(footer, 0, 6);
            plan.Text = "准备候选后，会在这里列出固定版本、改动文件与数据库迁移。\n\n本次范围：办公室应用与静态文件、北京后端和色块服务、已登记云静态站、已登记出库轮询器。\n\n其他独立服务只检查状态；小程序发布、平板 APK 安装不属于本次更新。";
            diagnosis.Text = "报错时显示失败步骤、日志证据与处理建议。未知原因会明确标注，程序不会自动删除锁、回滚数据库或重复发布。";
        }
        Label Card(TableLayoutPanel parent, int column, string title, string subtitle) {
            var panel = new Panel { Dock = DockStyle.Fill, BackColor = Color.White, Margin = new Padding(column == 0 ? 0 : 8, 0, column == 2 ? 0 : 8, 0), Padding = new Padding(14) };
            panel.Controls.Add(new Label { Text = title, Font = new Font(Font, FontStyle.Bold), AutoSize = true, Location = new Point(14, 9) });
            panel.Controls.Add(new Label { Text = subtitle, ForeColor = Theme.Muted, AutoSize = true, Location = new Point(14, 32) });
            var result = new Label { Text = "未检查", ForeColor = Theme.Muted, AutoSize = true, Location = new Point(14, 55) }; panel.Controls.Add(result); parent.Controls.Add(panel, column, 0); return result;
        }
        ListView List(string[] columns, int[] widths) {
            var list = new ListView { Dock = DockStyle.Fill, View = View.Details, FullRowSelect = true, GridLines = false, HideSelection = false, MultiSelect = false };
            for (int i = 0; i < columns.Length; i++) list.Columns.Add(columns[i], widths[i]);
            list.DoubleClick += delegate { if (list.SelectedItems.Count > 0) MessageBox.Show(String.Join("\n\n", list.SelectedItems[0].SubItems.Cast<ListViewItem.ListViewSubItem>().Select(s => s.Text)), "详细证据"); };
            return list;
        }
        RichTextBox TextArea() { return new RichTextBox { Dock = DockStyle.Fill, ReadOnly = true, BorderStyle = BorderStyle.None, BackColor = Color.White, ForeColor = Theme.Text, DetectUrls = false, WordWrap = true, Font = Font }; }
        void AddTab(string name, Control control) { var page = new TabPage(name) { Padding = new Padding(10) }; page.Controls.Add(control); tabs.TabPages.Add(page); }
        Button ActionButton(string text, bool primary) { return new Button { Text = text, AutoSize = true, Height = 35, Padding = new Padding(10, 0, 10, 0), Margin = new Padding(0, 0, 10, 0), FlatStyle = FlatStyle.Flat, BackColor = primary ? Theme.Gold : Color.White, ForeColor = primary ? Color.White : Theme.Text }; }
        Connection Current() { return new Connection { Host = host.Text.Trim(), Root = root.Text.Trim(), Port = port.Text.Trim(), IdentityFile = identityFile.Text.Trim() }; }
        void InvalidatePreparation() {
            ready = false; preparedId = ""; preparedRevision = ""; runId = ""; last = new Dictionary<string, object>();
            checks.Items.Clear(); steps.Items.Clear(); UpdateCards(); plan.Text = "连接配置已改变，请重新自检和准备候选。"; log.Clear(); diagnosis.Clear();
            status.Text = "连接配置已改变；尚未取得此服务器的检查或更新结果。"; stepCount.Text = "尚未发起任务"; Buttons();
        }
        void Buttons() {
            host.Enabled = root.Enabled = port.Enabled = identityFile.Enabled = !busy && !active;
            inspect.Enabled = !busy && !active; prepare.Enabled = !busy && !active && ready; deploy.Enabled = !busy && !active && preparedId.Length > 0 && preparedConnection == Current().Key;
            resume.Enabled = !busy; export.Enabled = !busy; progress.Style = busy || active ? ProgressBarStyle.Marquee : ProgressBarStyle.Continuous;
        }
        void SetBusy(bool value) { busy = value; Buttons(); }
        void OnUi(Action action) { if (!IsDisposed && IsHandleCreated) BeginInvoke(action); }
        async Task<Dictionary<string, object>> Request(Dictionary<string, object> request, bool stream) {
            var connection = Current();
            return await Task.Run(() => Transport.Request(connection, request, stream ? new Action<Dictionary<string, object>>(row => OnUi(() => AddCheck(row))) : null));
        }
        void AddCheck(Dictionary<string, object> row) {
            string code = Json.Text(row, "status");
            var item = new ListViewItem(new [] { Json.Text(row, "group"), Json.Text(row, "name"), StatusText(code), Json.Text(row, "detail") });
            item.ForeColor = code == "failed" ? Theme.Danger : code == "ok" ? Theme.Success : Theme.Muted; checks.Items.Add(item); UpdateCards();
        }
        void UpdateCards() {
            foreach (var pair in new [] { new { Name = "办公室服务器", Label = office }, new { Name = "leshine.cloud", Label = cloud }, new { Name = "leshine.work", Label = work } }) {
                var rows = checks.Items.Cast<ListViewItem>().Where(r => r.Text == pair.Name).ToArray();
                int failed = rows.Count(r => r.SubItems[2].Text == "未通过"), ok = rows.Count(r => r.SubItems[2].Text == "通过");
                pair.Label.Text = rows.Length == 0 ? "未检查" : String.Format("{0} 项通过 · {1} 项未通过 · {2} 项需关注", ok, failed, rows.Length - ok - failed);
                pair.Label.ForeColor = failed > 0 ? Theme.Danger : Theme.Muted;
            }
        }
        async Task Inspect() {
            SetBusy(true); ready = false; checks.Items.Clear(); UpdateCards(); tabs.SelectedIndex = 0;
            status.Text = "正在逐项检查办公室与两处云环境…";
            SaveSession();
            try {
                var report = await Request(new Dictionary<string, object> { { "action", "probe" } }, true);
                checks.Items.Clear(); foreach (var row in Json.Rows(report, "checks")) AddCheck(row);
                ready = report.ContainsKey("ready") && (bool)report["ready"];
                bool released = Json.Text(last, "status") == "succeeded" && Json.Text(last, "mode") == "deploy";
                status.Text = released ? (ready ? "更新成功；受管服务必要检查通过，关联服务状态见列表。" : "发布回执成功，但更新后检查有异常；请查看失败项。") : Json.Text(last, "status") == "failed" ? "本轮发布未完成；已刷新自检，请结合失败步骤与诊断处理。" : ready ? "必要检查通过，可以准备候选版本。关联服务的未知状态仍需关注。" : "存在未通过的必要检查，请先处理对应问题。";
                stepCount.Text = "检查于 " + Json.Text(report, "checked_at");
                SaveSession();
            } catch (Exception error) { ShowError(error); }
            finally { SetBusy(false); }
        }
        async Task StartRelease(string mode) {
            if (demo) return;
            if (mode == "deploy") {
                string confirmation = "固定版本：" + preparedRevision + "\n\n范围：办公室、leshine.cloud、leshine.work 与已登记关联组件。\n将由办公室统一入口切换服务，按候选检查结果执行必要数据库迁移。\n\n请确认已查看「更新内容」与迁移列表，开始本次更新？";
                if (MessageBox.Show(confirmation, "确认生产更新", MessageBoxButtons.OKCancel, MessageBoxIcon.Warning, MessageBoxDefaultButton.Button2) != DialogResult.OK) return;
            }
            SetBusy(true); ready = false;
            runId = Guid.NewGuid().ToString("N"); active = true; SaveSession();
            steps.Items.Clear(); log.Clear(); diagnosis.Clear(); status.Text = mode == "prepare" ? "正在远程准备候选版本…" : "已发起远程更新；服务器将重新自检后执行。"; tabs.SelectedIndex = 2;
            try {
                var request = new Dictionary<string, object> { { "action", "start" }, { "run_id", runId }, { "mode", mode } };
                if (mode == "deploy") request["prepared_run"] = preparedId;
                var result = await Request(request, false); RenderRun(result);
            } catch (Exception error) { active = false; preparedId = ""; ShowError(error); status.Text = "发起结果待核实。请恢复同一任务，勿重新发起更新。"; }
            finally { SetBusy(false); }
        }
        async Task RefreshRun(bool manual) {
            if (demo) return;
            SetBusy(true);
            try {
                var request = new Dictionary<string, object> { { "action", "status" } };
                if (runId.Length > 0) request["run_id"] = runId;
                var result = await Request(request, false); RenderRun(result); SaveSession();
                if (!active && Json.Text(result, "mode") == "deploy" && (Json.Text(result, "status") == "succeeded" || Json.Text(result, "status") == "failed")) {
                    SetBusy(false); await Inspect(); return;
                }
            } catch (Exception error) { active = false; ready = false; preparedId = ""; ShowError(error); status.Text = "连接中断或状态未知；办公室任务可能仍在运行，请恢复任务。"; }
            finally { SetBusy(false); }
        }
        void RenderRun(Dictionary<string, object> result) {
            last = result; string state = Json.Text(result, "status"); runId = Json.Text(result, "run_id"); active = state == "running" || state == "starting";
            steps.Items.Clear(); var events = Json.Rows(result, "events").ToArray();
            foreach (var group in events.Where(e => Json.Text(e, "kind") == "step").GroupBy(e => Json.Text(e, "key"))) {
                var step = group.Last(); string code = Json.Text(step, "status");
                var row = new ListViewItem(new [] { Json.Text(step, "label"), StatusText(code), code == "succeeded" ? "部署器已完成该步骤；未变化内容由原入口跳过" : code == "failed" ? "见错误诊断与日志；已完成步骤可能已生效" : "等待部署器返回；不使用估算百分比" });
                row.ForeColor = code == "failed" ? Theme.Danger : code == "succeeded" ? Theme.Success : Theme.Text; steps.Items.Add(row);
            }
            int done = steps.Items.Cast<ListViewItem>().Count(i => i.SubItems[1].Text == "已完成"); stepCount.Text = done + " 步已完成 / " + steps.Items.Count + " 步已报告";
            var candidate = events.LastOrDefault(e => Json.Text(e, "kind") == "plan");
            if (candidate != null) {
                var text = new System.Text.StringBuilder("候选版本：" + Json.Text(candidate, "revision") + "\n办公室原版本：" + Json.Text(candidate, "previous") + "\n\n改动文件（Git 状态：A 新增 / M 修改 / D 删除 / R 重命名）\n");
                object files; if (candidate.TryGetValue("files", out files)) foreach (object file in (System.Collections.IEnumerable)files) text.AppendLine(Convert.ToString(file));
                text.AppendLine("\n实际云端增量以准备日志中的 changed files / transfer bytes 为准。办公室差异为空，不代表云端无需同步。");
                var schema = events.LastOrDefault(e => Json.Text(e, "kind") == "schema");
                text.AppendLine("\n数据库目标：" + (schema == null ? "尚未核验" : Json.Text(schema, "target")));
                if (schema != null) text.AppendLine("待执行迁移：" + Json.Encode(schema["pending"]));
                text.AppendLine("\n更新范围：办公室应用及静态文件、北京后端和色块服务、主站和 PM 等已登记静态站、已登记出库轮询器。\n独立服务只检查状态；小程序审核发布、平板 APK、扩展浏览器安装另行处理。");
                plan.Text = text.ToString();
            }
            log.Text = Json.Text(result, "log");
            diagnosis.Text = "本轮任务：" + runId + "\n状态：" + StatusText(state) + "\n\n";
            object reasons; if (result.TryGetValue("diagnosis", out reasons)) foreach (object reason in (System.Collections.IEnumerable)reasons) diagnosis.AppendText(Convert.ToString(reason) + "\n\n");
            if (state == "prepared") { preparedId = runId; preparedRevision = Json.Text(result, "revision"); preparedConnection = Current().Key; tabs.SelectedIndex = 1; status.Text = "候选准备通过，尚未切换。请查看更新内容后确认。"; }
            else if (state == "succeeded") { preparedId = ""; status.Text = "部署器回执成功；正在核验更新后服务状态…"; }
            else if (state == "failed" || state == "unknown") { preparedId = ""; ready = false; tabs.SelectedIndex = 3; status.Text = "本轮" + StatusText(state) + "；请查看诊断。已完成步骤不会被当作整体成功。"; }
            else if (active) status.Text = "远程任务进行中 · " + runId.Substring(0, 8) + " · 可关闭窗口后恢复查看";
            else status.Text = "服务器尚无桌面任务。请先自检。";
            Buttons();
        }
        static string StatusText(string state) {
            switch (state) { case "ok": return "通过"; case "warning": return "需关注"; case "failed": return "未通过"; case "unknown": return "待核实"; case "running": return "执行中"; case "starting": return "启动中"; case "succeeded": return "已完成"; case "prepared": return "准备完成"; default: return "未验证"; }
        }
        void ShowError(Exception error) { diagnosis.Text = error.Message; tabs.SelectedIndex = 3; status.Text = "操作未完成。请查看错误诊断。"; }
        void SaveSession() {
            if (demo) return;
            try { Directory.CreateDirectory(Path.GetDirectoryName(stateFile)); File.WriteAllText(stateFile, Json.Encode(new { host = host.Text, root = root.Text, port = port.Text, identity_file = identityFile.Text, run_id = runId }), System.Text.Encoding.UTF8); }
            catch (Exception error) { diagnosis.AppendText("\n无法保存本机恢复位置：" + error.Message + "\n可通过服务器最新任务恢复。"); }
        }
        void LoadSession() {
            try { if (File.Exists(stateFile)) { var data = Json.Decode(File.ReadAllText(stateFile)); host.Text = Json.Text(data, "host"); root.Text = Json.Text(data, "root"); port.Text = Json.Text(data, "port"); identityFile.Text = Json.Text(data, "identity_file"); runId = Json.Text(data, "run_id"); if (runId.Length > 0) status.Text = "已保留上次任务编号。点击「恢复任务」读取服务器最新状态。"; } }
            catch (Exception error) { diagnosis.Text = "无法读取本机连接设置：" + error.Message; }
        }
        void Export() {
            using (var dialog = new SaveFileDialog { Filter = "文本报告|*.txt", FileName = "Ark-Deploy-Report.txt" }) {
                if (dialog.ShowDialog() != DialogResult.OK) return;
                var text = new System.Text.StringBuilder("方舟更新报告\n" + status.Text + "\n任务：" + runId + "\n\n" + plan.Text + "\n\n自检结果\n");
                foreach (ListViewItem item in checks.Items) text.AppendLine(String.Join(" | ", item.SubItems.Cast<ListViewItem.ListViewSubItem>().Select(s => s.Text)));
                text.AppendLine("\n诊断\n" + diagnosis.Text + "\n\n日志（末尾片段；完整日志留在办公室 .deploy_state/desktop/runs）\n" + log.Text);
                try { File.WriteAllText(dialog.FileName, text.ToString(), System.Text.Encoding.UTF8); } catch (Exception error) { ShowError(error); }
            }
        }
        public void ShowDemo() {
            headline.Text = "方舟更新中心 · 演示数据";
            RenderRun(Json.Decode("{\"status\":\"failed\",\"mode\":\"deploy\",\"run_id\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\",\"events\":[{\"kind\":\"plan\",\"revision\":\"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\",\"previous\":\"cccccccccccccccccccccccccccccccccccccccc\",\"files\":[\"M\\tbackend/app/example/service.py（演示）\",\"M\\tfrontend/src/views/example/Example.vue（演示）\"]},{\"kind\":\"schema\",\"target\":\"示例版本\",\"pending\":[]},{\"kind\":\"step\",\"key\":\"build\",\"label\":\"构建主站、PM 与浏览器扩展（演示）\",\"status\":\"succeeded\"},{\"kind\":\"step\",\"key\":\"office-activate\",\"label\":\"切换并验证办公室应用（演示）\",\"status\":\"succeeded\"},{\"kind\":\"step\",\"key\":\"beijing-activate\",\"label\":\"切换并验证北京后端（演示）\",\"status\":\"failed\"}],\"diagnosis\":[\"演示：北京后端健康检查未通过；办公室步骤已完成，不计为整体成功。\",\"演示：先检查北京服务状态与失败步骤日志，勿直接重复执行迁移。\"],\"log\":\"仅演示：办公室应用已核验；北京后端健康检查失败。没有连接任何服务器。\"}"));
            foreach (string group in new [] { "办公室服务器", "leshine.cloud", "leshine.work" }) {
                AddCheck(new Dictionary<string, object> { { "group", group }, { "name", "连接与服务状态" }, { "status", "ok" }, { "detail", "演示：连接成功，受管服务正常运行" } });
                AddCheck(new Dictionary<string, object> { { "group", group }, { "name", "应用与数据库健康" }, { "status", "ok" }, { "detail", "演示：健康检查通过" } });
            }
            AddCheck(new Dictionary<string, object> { { "group", "leshine.work" }, { "name", "openclaw（未纳管）" }, { "status", "unknown" }, { "detail", "未登记服务管理方式；未验证，不参与更新" } });
            status.Text = "演示模式 · 不连接服务器，不执行任何部署。"; stepCount.Text = "6 项通过 · 1 项未验证";
            tabs.SelectedIndex = 0;
            inspect.Enabled = prepare.Enabled = deploy.Enabled = resume.Enabled = false;
        }
    }
}
