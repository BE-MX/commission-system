package com.jeecg.modules.jmreport.controller;

import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Date;
import java.util.Map;

/**
 * 内网健康检查接口（不走 sa-token 鉴权，已在 SaTokenConfigure 白名单）
 *
 * 供 FastAPI 探活、监控系统使用。生产 Nginx 应限制 /internal/** 仅放行内网 IP。
 */
@RestController
@RequestMapping("/internal")
public class InternalHealthController {

    @GetMapping("/health")
    public ResponseEntity<Map<String, String>> health() {
        return ResponseEntity.ok(Map.of(
            "status", "UP",
            "service", "leshine-jmreport",
            "time", new Date().toString()
        ));
    }
}
