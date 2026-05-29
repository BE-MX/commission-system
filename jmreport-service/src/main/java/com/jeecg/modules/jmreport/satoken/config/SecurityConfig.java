package com.jeecg.modules.jmreport.satoken.config;

import com.jeecg.modules.jmreport.satoken.config.vo.User;
import org.springframework.beans.factory.config.BeanDefinition;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Role;
import org.springframework.stereotype.Component;


/**
 * 加载项目配置
 *
 * @author: jeecg-boot
 */
@Component("securityConfig")
@ConfigurationProperties(prefix = "spring.security")
@Role(BeanDefinition.ROLE_INFRASTRUCTURE)
public class SecurityConfig {
    private Boolean enable = true;
    /**
     * 登录账号和密码
     */
    private User user;

    public User getUser() {
        return user;
    }

    public void setUser(User user) {
        this.user = user;
    }

    public Boolean getEnable() {
        return enable;
    }

    public void setEnable(Boolean enable) {
        this.enable = enable;
    }
}
