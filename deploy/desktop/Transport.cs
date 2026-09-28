using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Web.Script.Serialization;

namespace ArkDeploy {
    internal static class Json {
        public static string Encode(object value) { return new JavaScriptSerializer { MaxJsonLength = 16000000 }.Serialize(value); }
        public static Dictionary<string, object> Decode(string value) { return new JavaScriptSerializer { MaxJsonLength = 16000000 }.Deserialize<Dictionary<string, object>>(value); }
        public static string Text(IDictionary<string, object> data, string key) { return data.ContainsKey(key) && data[key] != null ? Convert.ToString(data[key]) : ""; }
        public static IEnumerable<Dictionary<string, object>> Rows(IDictionary<string, object> data, string key) {
            if (!data.ContainsKey(key) || !(data[key] is System.Collections.IEnumerable)) yield break;
            foreach (object row in (System.Collections.IEnumerable)data[key]) {
                var item = row as Dictionary<string, object>;
                if (item != null) yield return item;
            }
        }
    }

    internal sealed class Connection {
        public string Host = "office-prod";
        public string Root = "D:/commission-system";
        public string Port = "";
        public string IdentityFile = "";
        public string Key { get { return Host + "|" + Root + "|" + Port + "|" + IdentityFile; } }
        public void Validate() {
            if (!Regex.IsMatch(Host, @"\A[a-zA-Z0-9_][a-zA-Z0-9_.@:-]*\z")) throw new Exception("SSH 主机只能填写已配置的别名或 user@host。");
            if (!Regex.IsMatch(Root, @"\A[A-Za-z]:[/\\]") || Regex.IsMatch(Root, "[\r\n\"%!&|<>^]")) throw new Exception("请填写 Windows 绝对安装路径；不能包含命令控制字符。");
            int port;
            if (Port.Length > 0 && (!Int32.TryParse(Port, out port) || port < 1 || port > 65535 || !Regex.IsMatch(Port, @"\A[0-9]+\z"))) throw new Exception("SSH 端口必须是 1–65535 的数字，留空则沿用 SSH 配置。");
            if (IdentityFile.Length > 0 && (IdentityFile.IndexOfAny(new [] { '\r', '\n', '\0' }) >= 0 || !File.Exists(IdentityFile))) throw new Exception("指定的本机私钥文件不存在。只填写文件路径，不填写密钥内容。");
        }
    }

    internal static class Transport {
        public static string Resource(string name) {
            using (Stream input = Assembly.GetExecutingAssembly().GetManifestResourceStream(name)) {
                if (input == null) throw new Exception("缺少应用资源：" + name);
                using (var reader = new StreamReader(input, Encoding.UTF8)) return reader.ReadToEnd();
            }
        }
        public static string Quote(string value) {
            var result = new StringBuilder("\"");
            int slashes = 0;
            foreach (char character in value) {
                if (character == '\\') { slashes++; continue; }
                result.Append('\\', character == '"' ? slashes * 2 + 1 : slashes);
                result.Append(character); slashes = 0;
            }
            result.Append('\\', slashes * 2); result.Append('"');
            return result.ToString();
        }
        public static string Ssh() {
            foreach (string entry in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(';')) {
                string folder = entry.Trim('"');
                if (folder.Length == 0) continue;
                string gitSsh = Path.GetFullPath(Path.Combine(folder, "../usr/bin/ssh.exe"));
                if (File.Exists(Path.Combine(folder, "git.exe")) && File.Exists(gitSsh)) return gitSsh;
            }
            string system = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "OpenSSH/ssh.exe");
            if (File.Exists(system)) return system;
            throw new Exception("本机没有 OpenSSH。请安装 Windows OpenSSH 客户端或 Git for Windows，并配置 office-prod。");
        }
        public static Dictionary<string, object> Request(Connection connection, Dictionary<string, object> request, Action<Dictionary<string, object>> check) {
            connection.Validate();
            request["root"] = connection.Root;
            var sources = new Dictionary<string, string>();
            foreach (string name in new [] { "desktop_checks", "desktop_host" }) sources[name] = Convert.ToBase64String(Encoding.UTF8.GetBytes(Resource(name)));
            string bootstrap = "import sys,json,base64,types\np=json.load(sys.stdin)\nfor n in ('desktop_checks','desktop_host'):\n m=types.ModuleType(n);sys.modules[n]=m;exec(compile(base64.b64decode(p['sources'][n]),n+'.py','exec'),m.__dict__)\nsys.modules['desktop_host'].main(p['request'],p['sources'])\n";
            string remote = "\"" + connection.Root.Replace('\\', '/').TrimEnd('/') + "/backend/.venv/Scripts/python.exe\" -X utf8 -c \"import sys,base64;exec(base64.b64decode(sys.stdin.readline()))\"";
            string options = connection.Port.Length > 0 ? " -p " + connection.Port : "";
            if (connection.IdentityFile.Length > 0) options += " -o IdentitiesOnly=yes -i " + Quote(connection.IdentityFile);
            var info = new ProcessStartInfo(Ssh(), "-T -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10 -o ServerAliveInterval=10 -o ServerAliveCountMax=2" + options + " " + connection.Host + " " + Quote(remote)) {
                UseShellExecute = false, CreateNoWindow = true, RedirectStandardInput = true,
                RedirectStandardOutput = true, RedirectStandardError = true, StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
            };
            using (var process = Process.Start(info)) {
                var output = Task.Run(() => {
                    Dictionary<string, object> response = null;
                    string line;
                    while ((line = process.StandardOutput.ReadLine()) != null) {
                        if (line.StartsWith("ARK_CHECK ") && check != null) check(Json.Decode(line.Substring(10)));
                        if (line.StartsWith("ARK_RESPONSE ")) response = Json.Decode(line.Substring(13));
                    }
                    return response;
                });
                var error = process.StandardError.ReadToEndAsync();
                process.StandardInput.WriteLine(Convert.ToBase64String(Encoding.UTF8.GetBytes(bootstrap)));
                process.StandardInput.Write(Json.Encode(new { request = request, sources = sources }));
                process.StandardInput.Close();
                if (!process.WaitForExit(Json.Text(request, "action") == "probe" ? 360000 : 45000)) {
                    process.Kill();
                    throw new Exception("SSH 查询超时。远端任务状态尚未核实，请使用「恢复任务」；不要重复发起更新。");
                }
                var result = output.GetAwaiter().GetResult();
                string stderr = error.GetAwaiter().GetResult();
                if (process.ExitCode != 0 || result == null) throw new Exception("SSH 连接或远端 Python 失败：\r\n" + stderr.Trim() + "\r\n核对 office-prod、隧道、主机指纹及服务器 Python 路径。若曾发起任务，请先恢复任务。");
                if (result.ContainsKey("error")) throw new Exception(Json.Text(result, "error"));
                return result;
            }
        }
    }
}
