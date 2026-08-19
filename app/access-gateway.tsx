export default function AccessGateway() {
  return (
    <main className="access-gateway">
      <section className="gateway-brand">
        <img src="/leshine-brand.jpg" alt="LESHINE 莱莎健康假发" />
        <div>
          <p>LESHINE</p>
          <h1>莱莎健康假发</h1>
          <span>34年健康假发的坚守者</span>
        </div>
      </section>
      <section className="gateway-login">
        <p className="gateway-kicker">请选择访问身份</p>
        <h2>不同账户，进入不同商城</h2>
        <p className="gateway-tip">正式版本登录后会自动识别账户身份，无需手动选择。</p>
        <div className="gateway-options">
          <a href="/retail">
            <i>零</i><div><strong>零售客户入口</strong><span>查看零售商品与零售价格</span></div><b>进入 ›</b>
          </a>
          <a href="/wholesale">
            <i>批</i><div><strong>批发商账户入口</strong><span>按账户等级显示批发价格与商品权限</span></div><b>登录 ›</b>
          </a>
        </div>
        <a className="gateway-admin" href="/admin">管理人员进入后台</a>
      </section>
    </main>
  );
}
