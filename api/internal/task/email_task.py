from datetime import timedelta

from celery import shared_task

from internal.extension.redis_extension import redis_client


@shared_task
def send_verification_email_task(
    email: str,
    scene: str,
    client_ip: str,
) -> None:
    from internal.exception import FailException
    from internal.service.email_service import EmailService
    from internal.service.mail_config_service import MailConfigService, send_smtp

    code = EmailService.generate_verification_code()
    subject, body, html = EmailService.build_verification_email_content(code, scene)
    try:
        cfg = MailConfigService().get_config()
        if not cfg.get("smtp_host"):
            raise RuntimeError("邮件发送未配置")
        send_smtp(cfg, recipients=[email], subject=subject, body=body, html=html)
        redis_client.setex(EmailService._code_key(email, scene), timedelta(seconds=EmailService.CODE_TTL_SECONDS), code)
        redis_client.setex(
            EmailService._send_cooldown_key(email, scene),
            timedelta(seconds=EmailService.SEND_COOLDOWN_SECONDS),
            "1",
        )
        redis_client.setex(
            EmailService._send_cooldown_ip_key(client_ip, scene),
            timedelta(seconds=EmailService.SEND_COOLDOWN_SECONDS),
            "1",
        )
        redis_client.delete(EmailService._verify_attempt_key(email, scene))
        redis_client.delete(EmailService._verify_lock_key(email, scene))
        redis_client.delete(EmailService._send_pending_key(email, scene))
        redis_client.delete(EmailService._send_pending_ip_key(client_ip, scene))
    except RuntimeError:
        redis_client.delete(EmailService._send_pending_key(email, scene))
        redis_client.delete(EmailService._send_pending_ip_key(client_ip, scene))
        raise FailException("邮件发送未配置，请联系管理员配置邮件通道")
    except Exception:
        redis_client.delete(EmailService._send_pending_key(email, scene))
        redis_client.delete(EmailService._send_pending_ip_key(client_ip, scene))
        raise
