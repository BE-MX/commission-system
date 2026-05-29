package com.jeecg.modules.jmreport.controller;

import cn.dev33.satoken.stp.StpUtil;
import com.jeecg.modules.jmreport.satoken.config.SecurityConfig;
import com.jeecg.modules.jmreport.satoken.util.AjaxRequestUtils;
import jakarta.servlet.http.HttpSession;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;

import java.net.URLEncoder;

/**
 * 积木报表-设置默认首页跳转
 */
@Controller
public class LoginController {
    private Logger logger = LoggerFactory.getLogger(LoginController.class);
    public final static String LOGIN_PAGE = "/login/login.html";

    @Autowired
    SecurityConfig securityConfig;

    /**
     * 登录请求
     *
     * @param username
     * @param password
     * @param req
     * @return
     */
    @GetMapping("/doLogin")
    public String login(@RequestParam String username, @RequestParam String password, jakarta.servlet.http.HttpServletRequest req) {
        logger.info("登录请求，用户名：" + username + "，密码：" + password);
        // 此处通过yml配置文件获取登录账号和密码，实际项目中请从数据库读取进行验证
        if (securityConfig.getUser().getName().equals(username) && securityConfig.getUser().getPassword().equals(password)) {
            StpUtil.login(securityConfig.getUser().getName());
            logger.info("登录成功，当前会话tokeName={}, tokenValue={}", StpUtil.getTokenName(), StpUtil.getTokenValue());

            // 设置登录来源，方便退出登录时区分
            AjaxRequestUtils.setLoginSessionInfo();
            return "jmreport/list";
        }else{
            logger.error("登录失败，用户名或密码错误");
            // 返回密码错误提示，需进行URL编码
            return "redirect:" + LOGIN_PAGE + "?error=1";
        }
    }


    /**
     * 首页跳转
     *
     * @param model
     * @return
     */
    @GetMapping("/")
    public String index(Model model) {
        model.addAttribute("name", "jimureport");
        return "jmreport/list"; // 视图重定向 - 跳转
    }

    /**
     * 查询登录状态
     *
     * @return
     */
    @RequestMapping("/isLogin")
    public String isLogin() {
        logger.info("查询登录状态:{}", StpUtil.getTokenInfo());
        return "当前会话是否登录：" + StpUtil.isLogin();
    }

    /**
     * 退出登录
     *
     * @return
     */
    @RequestMapping("/logout")
    public String logout() {
        StpUtil.logout();
        return "redirect:" + LOGIN_PAGE;
    }
}