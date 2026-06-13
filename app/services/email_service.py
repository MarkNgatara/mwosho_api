import smtplib
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from app.config import settings


def _smtp_send(msg: MIMEMultipart, to_email: str) -> None:
    with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(settings.GMAIL_USER, settings.GMAIL_APP_PASSWORD)
        smtp.sendmail(settings.GMAIL_USER, to_email, msg.as_string())


def _configured() -> bool:
    return bool(settings.GMAIL_USER and settings.GMAIL_APP_PASSWORD)


def send_job_complete_email(
    to_email: str,
    full_name: str | None,
    filename: str,
    download_token: str,
    score_before: float | None,
    score_after: float | None,
    total_rows: int | None,
) -> None:
    name = full_name or to_email.split("@")[0]
    download_url = f"{settings.FRONTEND_URL}/download/{download_token}"
    improvement = ""
    if score_before is not None and score_after is not None:
        delta = round(score_after - score_before)
        sign  = "+" if delta >= 0 else ""
        improvement = f"{sign}{delta} pts  ({score_before:.0f} → {score_after:.0f})"
    rows_str = f"{total_rows:,}" if total_rows else "—"

    if not _configured():
        print(f"[email] job_complete DEV link for {to_email}: {download_url}")
        return

    html = f"""
    <!DOCTYPE html>
    <html>
    <body style="margin:0;padding:0;background:#f8fafc;font-family:'Segoe UI',Arial,sans-serif;">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr><td align="center" style="padding:40px 16px;">
          <table width="520" cellpadding="0" cellspacing="0"
                 style="background:#fff;border-radius:16px;box-shadow:0 4px 24px rgba(0,0,0,.08);overflow:hidden;">
            <tr>
              <td style="background:#2563eb;padding:28px 40px;text-align:center;">
                <span style="color:#fff;font-size:22px;font-weight:900;letter-spacing:-1px;">Mwosho</span>
              </td>
            </tr>
            <tr>
              <td style="padding:40px;">
                <p style="margin:0 0 6px;font-size:15px;color:#64748b;">Hi {name},</p>
                <h2 style="margin:0 0 20px;font-size:22px;color:#0f172a;">Your file is ready to download</h2>
                <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:12px;padding:20px 24px;margin-bottom:28px;">
                  <p style="margin:0 0 10px;font-size:14px;font-weight:700;color:#15803d;">Cleaning complete</p>
                  <table width="100%" cellpadding="4" cellspacing="0" style="font-size:14px;color:#374151;">
                    <tr><td style="color:#6b7280;">File</td><td style="font-weight:600;">{filename}</td></tr>
                    <tr><td style="color:#6b7280;">Rows processed</td><td style="font-weight:600;">{rows_str}</td></tr>
                    {"<tr><td style='color:#6b7280;'>Quality score</td><td style='font-weight:600;color:#16a34a;'>" + improvement + "</td></tr>" if improvement else ""}
                  </table>
                </div>
                <div style="text-align:center;margin-bottom:32px;">
                  <a href="{download_url}"
                     style="display:inline-block;background:#2563eb;color:#fff;font-size:16px;
                            font-weight:700;padding:16px 40px;border-radius:12px;text-decoration:none;">
                    Download Cleaned File
                  </a>
                </div>
                <div style="background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:14px 18px;margin-bottom:24px;">
                  <p style="margin:0;font-size:13px;color:#92400e;">
                    ⏱ <strong>This link expires in 1 hour.</strong> After that, your file is permanently deleted
                    from our servers. Not happy with the result? Use the AI chatbox on the job page before downloading.
                  </p>
                </div>
                <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:14px 18px;">
                  <p style="margin:0 0 6px;font-size:12px;font-weight:700;color:#475569;text-transform:uppercase;letter-spacing:.5px;">
                    Data Privacy Promise
                  </p>
                  <p style="margin:0;font-size:13px;color:#64748b;line-height:1.6;">
                    Your data <strong>never rests on our servers.</strong> Files pass through Mwosho
                    for processing only and are permanently wiped after download or expiry.
                    Compliant with GDPR · CCPA · Kenya DPA 2019 · POPIA · LGPD.
                  </p>
                </div>
              </td>
            </tr>
            <tr>
              <td style="padding:20px 40px;background:#f8fafc;border-top:1px solid #e2e8f0;
                         font-size:12px;color:#94a3b8;text-align:center;">
                &copy; {__import__('datetime').date.today().year} Mwosho &mdash;
                Your data is never stored &mdash;
                <a href="{settings.FRONTEND_URL}/privacy" style="color:#94a3b8;">Privacy Policy</a>
              </td>
            </tr>
          </table>
        </td></tr>
      </table>
    </body>
    </html>
    """

    plain = (
        f"Hi {name},\n\nYour cleaned file '{filename}' is ready.\n\n"
        f"Download: {download_url}\n\n"
        f"⚠ This link expires in 1 hour. After that, your file is permanently deleted.\n\n"
        f"— Mwosho"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Your cleaned file is ready — {filename}"
    msg["From"]    = f"Mwosho <{settings.GMAIL_USER}>"
    msg["To"]      = to_email
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    threading.Thread(target=_smtp_send, args=(msg, to_email), daemon=True).start()


def send_otp_email(to_email: str, otp: str, full_name: str | None = None) -> None:
    name = full_name or to_email.split("@")[0]

    if not _configured():
        print(f"[email] SMTP not configured -- DEV OTP for {to_email} is: {otp}")
        return

    html = f"""
    <!DOCTYPE html>
    <html>
    <body style="margin:0;padding:0;background:#f8fafc;font-family:'Segoe UI',Arial,sans-serif;">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr><td align="center" style="padding:40px 16px;">
          <table width="480" cellpadding="0" cellspacing="0"
                 style="background:#fff;border-radius:16px;box-shadow:0 4px 24px rgba(0,0,0,.08);overflow:hidden;">
            <tr>
              <td style="background:#2563eb;padding:28px 40px;text-align:center;">
                <span style="color:#fff;font-size:22px;font-weight:900;letter-spacing:-1px;">Mwosho</span>
              </td>
            </tr>
            <tr>
              <td style="padding:40px;">
                <p style="margin:0 0 8px;font-size:15px;color:#64748b;">Hi {name},</p>
                <h2 style="margin:0 0 24px;font-size:22px;color:#0f172a;">Verify your email address</h2>
                <p style="margin:0 0 28px;font-size:15px;color:#475569;line-height:1.6;">
                  Enter the code below in the Mwosho app to confirm your account.
                  It expires in <strong>10 minutes</strong>.
                </p>
                <div style="text-align:center;margin:0 0 32px;">
                  <span style="display:inline-block;background:#eff6ff;border:2px dashed #93c5fd;
                               border-radius:12px;padding:18px 40px;font-size:36px;font-weight:900;
                               letter-spacing:10px;color:#1d4ed8;">{otp}</span>
                </div>
                <p style="margin:0;font-size:13px;color:#94a3b8;">
                  If you didn't create an account you can safely ignore this email.
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:20px 40px;background:#f8fafc;border-top:1px solid #e2e8f0;
                         font-size:12px;color:#94a3b8;text-align:center;">
                &copy; {__import__('datetime').date.today().year} Mwosho &mdash; AI-powered data cleaning
              </td>
            </tr>
          </table>
        </td></tr>
      </table>
    </body>
    </html>
    """

    plain = f"Hi {name},\n\nYour Mwosho verification code is: {otp}\n\nExpires in 10 minutes.\n"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Your Mwosho verification code"
    msg["From"] = f"Mwosho <{settings.GMAIL_USER}>"
    msg["To"] = to_email
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))

    _smtp_send(msg, to_email)
