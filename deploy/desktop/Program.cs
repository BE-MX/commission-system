using System;
using System.Drawing;
using System.IO;
using System.Windows.Forms;

namespace ArkDeploy {
    internal static class Program {
        [STAThread]
        static int Main(string[] args) {
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            if (args.Length == 2 && args[0] == "--self-test") return SelfTest.Run(args[1]);
            bool demo = args.Length > 0 && (args[0] == "--demo" || args[0] == "--screenshot");
            try {
                var form = new ConsoleForm(demo);
                if (demo) form.Shown += delegate {
                    form.ShowDemo();
                    if (args.Length == 2 && args[0] == "--screenshot") {
                        form.Refresh(); Application.DoEvents();
                        using (var bitmap = new Bitmap(form.Width, form.Height)) { form.DrawToBitmap(bitmap, new Rectangle(Point.Empty, form.Size)); bitmap.Save(Path.GetFullPath(args[1])); }
                        form.Close();
                    }
                };
                Application.Run(form); return 0;
            } catch (Exception error) { MessageBox.Show(error.Message, "方舟更新中心启动失败", MessageBoxButtons.OK, MessageBoxIcon.Error); return 1; }
        }
    }
}
