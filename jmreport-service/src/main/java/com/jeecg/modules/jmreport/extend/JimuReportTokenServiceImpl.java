package com.jeecg.modules.jmreport.extend;

import cn.dev33.satoken.context.SaHolder;
import cn.dev33.satoken.exception.NotLoginException;
import cn.dev33.satoken.stp.StpUtil;
import com.jeecg.modules.jmreport.satoken.config.SecurityConfig;
import com.jeecg.modules.jmreport.satoken.util.AjaxRequestUtils;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import jakarta.servlet.http.HttpServletRequest;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang3.StringUtils;
import org.jeecg.modules.jmreport.api.JmReportTokenServiceI;
import org.jeecg.modules.jmreport.common.constant.JmConst;
import org.jeecg.modules.jmreport.common.expetion.JimuReportException;
import org.jeecg.modules.jmreport.common.util.JimuSpringContextUtils;
import org.jeecg.modules.jmreport.common.util.OkConvertUtils;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.util.List;

/**
 * 方舟 × jimureport 鉴权适配器
 *
 * 取代 example 默认的"用户名/密码登录 → sa-token 内部 UUID"流程：
 *   - getToken      : 从 ?token=xxx 或 Authorization Bearer 拿方舟 access_token
 *   - verifyToken   : 用 ARK_JWT_SECRET 解签;成功则把方舟用户名通过 StpUtil.login(username)
 *                     注入 sa-token 上下文,jimureport 内部所有需要 sa-token 的逻辑无缝跑通
 *   - getUsername / getRoles / getPermissions : 从方舟 JWT payload 拿
 *
 * 方舟 access_token payload (grep 验证 2026-05-29):
 *   { sub: <user.id>, username, roles[], permissions[], must_change_password, exp, iat }
 */
@Slf4j
@Component
public class JimuReportTokenServiceImpl implements JmReportTokenServiceI {

    @Autowired
    SecurityConfig securityConfig;

    /**
     * 与方舟 backend/.env 的 JWT_SECRET_KEY 完全一致;启动时通过 ark.jwt.secret 注入。
     */
    @Value("${ark.jwt.secret:please-set-ark-jwt-secret-in-env}")
    private String arkJwtSecret;

    @Override
    public String getToken(HttpServletRequest request) {
        // 1. iframe 嵌入 / 浏览器首次进入：从 URL ?token=xxx 取（最高优先级）
        //    一定要在 StpUtil.getTokenValue 之前，否则 sa-token 残留的 UUID
        //    会被当成 token 喂给 verifyToken，JWT parse 直接失败
        String token = null;
        if (request != null) {
            token = request.getParameter("token");
            if (StringUtils.isEmpty(token)) {
                String auth = request.getHeader("Authorization");
                if (auth != null && auth.startsWith("Bearer ")) {
                    token = auth.substring(7);
                }
            }
            if (StringUtils.isEmpty(token)) {
                token = request.getHeader("X-Access-Token");
            }
        }

        // 2. URL/Header 都没拿到才去 sa-token 上下文（用于 verifyToken 内 setTokenValue 后的同 request 二次调用）
        if (StringUtils.isEmpty(token)) {
            try {
                token = StpUtil.getTokenValue();
            } catch (Exception ignored) {}
        }

        if (log.isDebugEnabled() && StringUtils.isNotEmpty(token)) {
            log.debug("ARK token from request: {}...",
                token.substring(0, Math.min(20, token.length())));
        }
        return token;
    }

    @Override
    public String getUsername(String token) {
        if (StringUtils.isEmpty(token)) return null;
        try {
            return parseArkJwt(token).get("username", String.class);
        } catch (Exception e) {
            log.warn("getUsername failed: {}", e.getMessage());
            return null;
        }
    }

    @Override
    public String[] getRoles(String token) {
        if (StringUtils.isEmpty(token)) return new String[0];
        try {
            Object roles = parseArkJwt(token).get("roles");
            return toStringArray(roles);
        } catch (Exception e) {
            return new String[0];
        }
    }

    @Override
    public String[] getPermissions(String token) {
        if (StringUtils.isEmpty(token)) return new String[0];
        try {
            Object perms = parseArkJwt(token).get("permissions");
            return toStringArray(perms);
        } catch (Exception e) {
            return new String[0];
        }
    }

    @Override
    public Boolean verifyToken(String token) {
        // 调试旁路
        if (securityConfig.getEnable() != null && !securityConfig.getEnable()) {
            return true;
        }
        if (StringUtils.isEmpty(token)) {
            return handleUnauthorized();
        }

        try {
            Claims claims = parseArkJwt(token);
            String username = claims.get("username", String.class);
            if (StringUtils.isEmpty(username)) {
                log.warn("ARK token missing username claim");
                return handleUnauthorized();
            }

            // 把方舟用户名注入 sa-token 上下文。
            // sa-token 之后的 StpUtil.checkLogin / getLoginIdAsString 全靠这一步。
            // 重复 login 同一用户名是幂等的(is-share=false 时 sa-token 会复用旧会话或建新会话,这里不关心)。
            try {
                StpUtil.login(username);
                StpUtil.setTokenValue(token);   // 让后续 StpUtil.getTokenValue() 拿到方舟 token 而非 sa-token UUID
            } catch (Exception e) {
                log.warn("StpUtil.login bind failed (continuing): {}", e.getMessage());
            }

            log.debug("verifyToken ok, user={}", username);
            return true;
        } catch (Exception e) {
            log.warn("verifyToken parse failed: {}", e.getMessage());
            return handleUnauthorized();
        }
    }

    @Override
    public String getTenantId() {
        // 方舟暂无多租户概念,保持 example 默认行为(从 header/param 取)以兼容 jimureport 内部多租户字段
        String headerTenantId = null;
        HttpServletRequest request = JimuSpringContextUtils.getHttpServletRequest();
        if (request != null) {
            headerTenantId = request.getHeader(JmConst.HEADER_TENANT_KEY);
            if (OkConvertUtils.isEmpty(headerTenantId)) {
                headerTenantId = request.getHeader(JmConst.HEADER_TENANT_ID);
            }
            if (OkConvertUtils.isEmpty(headerTenantId)) {
                headerTenantId = request.getParameter(JmConst.TENANT_ID);
            }
        }
        return headerTenantId;
    }

    // ── 私有 ──────────────────────────────────────────────

    private Claims parseArkJwt(String token) {
        SecretKey key = Keys.hmacShaKeyFor(arkJwtSecret.getBytes(StandardCharsets.UTF_8));
        return Jwts.parser().verifyWith(key).build()
            .parseSignedClaims(token).getPayload();
    }

    private static String[] toStringArray(Object value) {
        if (value == null) return new String[0];
        if (value instanceof String s) {
            return s.isBlank() ? new String[0] : s.split(",");
        }
        if (value instanceof List<?> list) {
            return list.stream().map(String::valueOf).toArray(String[]::new);
        }
        if (value instanceof Iterable<?> it) {
            java.util.List<String> result = new java.util.ArrayList<>();
            for (Object o : it) result.add(String.valueOf(o));
            return result.toArray(new String[0]);
        }
        return new String[]{ String.valueOf(value) };
    }

    private boolean handleUnauthorized() {
        // 浏览器直接访问:重定向到 example 的 login 页
        // AJAX:返回 false 让 interceptor 出 401
        try {
            HttpServletRequest req = JimuSpringContextUtils.getHttpServletRequest();
            if (req != null && !AjaxRequestUtils.isAjaxRequest(req)) {
                JimuSpringContextUtils.getHttpServletResponse().sendRedirect("/login/login.html");
            }
        } catch (Exception ignored) {}
        return false;
    }
}
