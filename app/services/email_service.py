import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from app.config import settings


def send_otp_email(to_email: str, otp: str, full_name: str | None = None) -> None:
    name = full_name or to_email.split("@")[0]

    if not settings.GMAIL_USER or settings.GMAIL_USER == "your-email@gmail.com" or not settings.GMAIL_APP_PASSWORD:
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

    with smtplib.SMTP("smtp.gmail.com", 587) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(settings.GMAIL_USER, settings.GMAIL_APP_PASSWORD)
        smtp.sendmail(settings.GMAIL_USER, to_email, msg.as_string())
