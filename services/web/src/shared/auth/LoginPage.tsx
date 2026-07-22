import { useState } from "react";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { useEndUserAuth } from "./EndUserAuth";
import { readRecentUsernames } from "./recentAccounts";

export function LoginPage() {
  const { login, register, switchingAccount } = useEndUserAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [recent] = useState(() => readRecentUsernames());

  const submit = async () => {
    setError(null);
    setBusy(true);
    try {
      if (mode === "login") {
        await login(username.trim(), password);
      } else {
        await register(username.trim(), password);
      }
    } catch {
      setError(
        mode === "login"
          ? "登录失败，请检查用户名或密码"
          : "注册失败，用户名可能已占用",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm rounded-xl border border-border bg-card/80 p-6 shadow-xl">
        <h1 className="text-xl font-semibold text-foreground">Agent Platform</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {switchingAccount
            ? "切换账号：选择或输入另一用户，密码仍需验证"
            : "登录后可跨设备查看并继续自己的会话历史"}
        </p>
        {mode === "login" && recent.length > 0 ? (
          <div className="mt-4">
            <p className="mb-1.5 text-[11px] text-muted-foreground">最近使用</p>
            <div className="flex flex-wrap gap-1.5">
              {recent.map((name) => (
                <button
                  key={name}
                  type="button"
                  className="rounded-md border border-input bg-background px-2 py-1 text-xs text-foreground hover:bg-muted"
                  onClick={() => {
                    setUsername(name);
                    setPassword("");
                    setError(null);
                  }}
                >
                  {name}
                </button>
              ))}
            </div>
          </div>
        ) : null}
        <form
          className="mt-6 flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <Input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="用户名"
            autoComplete="username"
            className="border-input bg-background"
          />
          <Input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="密码（至少 6 位）"
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            className="border-input bg-background"
          />
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
          <Button
            type="submit"
            disabled={busy || !username.trim() || password.length < 6}
          >
            {busy ? "请稍候…" : mode === "login" ? "登录" : "注册并登录"}
          </Button>
        </form>
        <button
          type="button"
          className="mt-4 text-sm text-primary hover:underline"
          onClick={() => {
            setMode(mode === "login" ? "register" : "login");
            setError(null);
          }}
        >
          {mode === "login" ? "没有账号？注册" : "已有账号？登录"}
        </button>
      </div>
    </div>
  );
}
