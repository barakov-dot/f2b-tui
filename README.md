# Fail2ban TUI

Консольная панель Fail2ban для Ubuntu 22.04+ без Docker, веб-сервера или сторонних Python-библиотек.

## Возможности

- Статус Fail2ban, список jail и заблокированных IP
- Бан и разбан одного IPv4/IPv6 с подтверждением
- Изменение `bantime`, `findtime` (секунды), `maxretry` (число) в отдельном конфиге
- Проверка конфигурации, reload, restart, последние 250 строк логов
- Меню со стрелками, Enter, q; внутри логов PgUp/PgDn

## Установка из GitHub

После публикации проекта замените `OWNER` на имя GitHub-пользователя (и выберите тег релиза):

```bash
sudo apt update && sudo apt install -y fail2ban python3 curl tar
VERSION=v0.1.0
OWNER=OWNER
curl -fL "https://github.com/${OWNER}/fail2ban-tui/archive/refs/tags/${VERSION}.tar.gz" -o /tmp/fail2ban-tui.tar.gz
mkdir -p /tmp/fail2ban-tui-install
tar -xzf /tmp/fail2ban-tui.tar.gz -C /tmp/fail2ban-tui-install --strip-components=1
# Проверьте содержимое install.sh и f2b.py перед запуском с sudo:
sudo bash /tmp/fail2ban-tui-install/install.sh
sudo f2b
```

Для повторной установки/обновления скачайте новый тег и повторите установку. Не запускайте произвольные скрипты напрямую из сети под root без проверки.

## Локальная установка

```bash
sudo apt install -y fail2ban python3
sudo bash install.sh
sudo f2b
```

## Удаление

```bash
sudo bash uninstall.sh
```

Изменения настроек лежат в `/etc/fail2ban/jail.d/99-f2b-tui.local` и при удалении **сохраняются**, чтобы избежать неожиданного изменения защиты. Сервис Fail2ban не удаляется.

## Предосторожности

Приложение требует root для управления Fail2ban, поэтому запускайте `sudo f2b` только из доверенной копии. Не используйте в незащищённой SSH-сессии. Утилита не настраивает firewall, SSH, VLESS или Remnawave. Перед изменениями сделайте резервную копию `/etc/fail2ban`.

Примечание: менеджер записывает целочисленные секунды и количество попыток в отдельный override-файл; существующие настройки в других файлах не переписывает. Если конфигурация не проходит тест после записи, верните настройки из резервной копии или исправьте указанный override-файл.
