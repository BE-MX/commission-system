using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

namespace ArkDeploy {
    internal static class SelfTest {
        static void Assert(bool value, string message) { if (!value) throw new Exception(message); }
        static T Field<T>(ConsoleForm form, string name) { return (T)typeof(ConsoleForm).GetField(name, BindingFlags.Instance | BindingFlags.NonPublic).GetValue(form); }
        public static int Run(string output) {
            var results = new List<string>();
            try {
                foreach (string host in new [] { "office-prod", "admin@example.test" }) new Connection { Host = host }.Validate();
                foreach (string host in new [] { "-oProxyCommand=bad", "office & whoami", "office\nwhoami" }) {
                    bool rejected = false; try { new Connection { Host = host }.Validate(); } catch { rejected = true; } Assert(rejected, "Unsafe host accepted");
                }
                foreach (string root in new [] { "D:/repo%PATH%", "D:/repo\" & whoami", "relative", "D:/repo\n" }) {
                    bool rejected = false; try { new Connection { Root = root }.Validate(); } catch { rejected = true; } Assert(rejected, "Unsafe root accepted");
                }
                results.Add("PASS SSH target/path injection checks");
                foreach (string port in new [] { "0", "65536", "22 -oProxyCommand=bad", "-1" }) {
                    bool rejected = false; try { new Connection { Port = port }.Validate(); } catch { rejected = true; } Assert(rejected, "Unsafe port accepted");
                }
                new Connection { Port = "2223" }.Validate();
                results.Add("PASS explicit SSH port validation");
                Assert(Transport.Quote("a\"b") == "\"a\\\"b\"", "Quote failed");
                Assert(Transport.Quote("a\\") == "\"a\\\\\"", "Trailing slash quoting failed");
                results.Add("PASS Windows argument quoting");
                using (var form = new ConsoleForm(true)) {
                    Assert(!Field<Button>(form, "deploy").Enabled, "Deploy enabled without preparation");
                    var render = typeof(ConsoleForm).GetMethod("RenderRun", BindingFlags.Instance | BindingFlags.NonPublic);
                    render.Invoke(form, new object[] { Json.Decode("{\"status\":\"prepared\",\"run_id\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\",\"revision\":\"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\",\"events\":[]}") });
                    Assert(Field<Button>(form, "deploy").Enabled, "Prepared result cannot deploy");
                    Field<TextBox>(form, "host").Text = "different-office";
                    Assert(!Field<Button>(form, "deploy").Enabled, "Changing server retained prepared authorization");
                    render.Invoke(form, new object[] { Json.Decode("{\"status\":\"failed\",\"run_id\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\",\"events\":[{\"kind\":\"step\",\"key\":\"office\",\"label\":\"Office\",\"status\":\"succeeded\"},{\"kind\":\"step\",\"key\":\"cloud\",\"label\":\"Cloud\",\"status\":\"failed\"}]}") });
                    Assert(!Field<Button>(form, "deploy").Enabled && Field<ListView>(form, "steps").Items.Count == 2, "Partial failure handling failed");
                    render.Invoke(form, new object[] { Json.Decode("{\"status\":\"succeeded\",\"mode\":\"deploy\",\"run_id\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\",\"events\":[]}") });
                    Field<TextBox>(form, "root").Text = "D:/different-repo";
                    Assert(Field<Dictionary<string, object>>(form, "last").Count == 0, "Old server success retained on new connection");
                    results.Add("PASS prepare gating, connection invalidation, partial failure presentation");
                }
                results.Add("PASS embedded Python sources and theme loaded"); File.WriteAllLines(output, results); return 0;
            } catch (Exception error) { results.Add("FAIL " + error); File.WriteAllLines(output, results); return 1; }
        }
    }
}
