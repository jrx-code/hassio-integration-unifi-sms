# UniFi 5G SMS dla Home Assistant

[English](README.md) | **Polski**

Wysyłanie i odbieranie SMS-ów w Home Assistant przez modem komórkowy **UniFi U5G**
(testowane na U5G-Max-Outdoor, firmware 7.5.3) zaadoptowany przez bramę UniFi. Bez
dodatkowego sprzętu i bez bramki SMS w chmurze, działa także wtedy, gdy padnie
internet stacjonarny.

## Jak to działa

Interfejs UniFi nie ma funkcji SMS, ale demon modemu na U5G (`uiwwand`) ją ma.
Integracja utrzymuje połączenie SSH z modemem i:

- **wysyła** metodą `send-sms` demona, dzieląc tekst na części po 64 bajty (limit
  firmware);
- **odbiera** przez jednoliniowy hook w skrypcie zdarzeń SMS modemu, który zapisuje
  każdą przychodzącą wiadomość w `/tmp/unifi_sms`. Integracja co 15 sekund odczytuje
  i usuwa te pliki. System plików modemu działa w RAM-ie, więc hook jest instalowany
  od nowa przy każdym nowym połączeniu SSH, także po restarcie modemu. Usunięcie
  integracji zdejmuje hook.

Szczegóły i osobliwości firmware: [docs/u5g-sms-internals.md](docs/u5g-sms-internals.md) (po angielsku).

## Obsługiwane urządzenia

| Urządzenie | Stan |
|---|---|
| UniFi 5G Max Outdoor (U5G-Max-Outdoor) | **przetestowane**, firmware 7.5.3 |
| UniFi 5G Max (wewnętrzny), UniFi 5G Backup (U5G) | powinno działać: ten sam demon `uiwwand` i te same metody ubus według [publicznego opisu](https://gist.github.com/keyz182/96a901d5ba1bf5f4b9701f5eba8729ad); nie testowane tutaj |
| UniFi LTE Backup Pro (U-LTE-Pro) | nieobsługiwane: nie ma `uiwwand`. SMS-y są dostępne w wewnętrznym module Sierra Legato przez drugi skok SSH i `cm sms ...` ([przykład](https://github.com/CppBunny/unifi_sms_gateway)), co wymagałoby osobnego backendu |
| UniFi Mobile Router (rodzina UMR) | nieobsługiwane: brak znanej metody odczytu i wysyłki SMS; prośby społeczności o tę funkcję nie mają odpowiedzi Ubiquiti ([wątek](https://community.ui.com/questions/UMR-Industrial-SMS/68d10331-f138-4e4e-90ef-e864eb91a639)) |
| Dream Router 5G Max (UDR-5G-Max) | nieznane: wbudowany modem, brak publicznych informacji o dostępie do SMS |

## Wymagania

- U5G zaadoptowany w UniFi Network, z aktywną kartą SIM z usługą SMS.
- Włączone Device SSH w UniFi Network: UniFi Devices → Device Updates and Settings
  (lewy dolny róg) → Device SSH Settings → Device SSH Authentication. W UniFi Network
  starszym niż 9.2.87: Settings → System → Advanced → Device Authentication.
  Ustawienie dotyczy wszystkich zaadoptowanych urządzeń; zalecane logowanie tylko
  kluczem.
- Home Assistant musi widzieć port 22 na adresie IP modemu. Na UDM modem jest
  w sieci wewnętrznej, do której ruch z LAN-u jest routowany.

## Instalacja

HACS → Integracje → ⋮ → Własne repozytoria → dodaj to repozytorium jako
*Integration*, zainstaluj **UniFi 5G SMS**, zrestartuj Home Assistant.

## Konfiguracja

1. Ustawienia → Urządzenia i usługi → Dodaj integrację → **UniFi 5G SMS**.
2. **Adres IP modemu**: UniFi Network → UniFi Devices → modem 5G → Overview →
   IP Address. **Użytkownik Device SSH**: strona Device SSH Settings opisana wyżej.
   Zostaw klucz prywatny pusty, integracja wygeneruje własny.
3. Dodaj pokazany klucz publiczny w Device SSH Settings → SSH Keys. Modem pobiera go
   do minuty. Zatwierdź. Jeśli logowanie się nie uda, na tym samym ekranie można
   poprawić adres lub nazwę użytkownika; klucz zostaje ten sam.

Home Assistant łączy się wtedy bezpośrednio z modemem przez SSH i utrzymuje
połączenie. Klucz hosta modemu jest zapamiętywany przy pierwszym połączeniu; jeśli
się zmieni, integracja prosi o ponowne uwierzytelnienie i przyjmuje nowy klucz tylko
po zaznaczeniu pola.

Gdy później zmieni się IP modemu lub nazwa użytkownika: menu ⋮ integracji → ponowna
konfiguracja (w angielskim UI **Reconfigure**). Klucz i zapamiętany klucz hosta
zostają.

To, dokąd integracja się łączy i czy działa, widać na stronie urządzenia: sensor
*Połączenie z modemem* (host, port, użytkownik, odcisk klucza hosta) i sensor
*Hook odbioru*. **Pobierz diagnostykę** daje to samo z ukrytymi kluczami i numerami.

## Opcje

| Opcja | |
|---|---|
| Domyślni odbiorcy | numery, na które wysyła encja powiadomień |
| Zaufani nadawcy | przychodzące SMS-y dostają `trusted: true/false`; sprawdzaj to w automatyzacjach reagujących na komendy SMS |
| Ignoruj SMS-y od innych nadawców | SMS-y od niezaufanych nadawców nie wywołują zdarzeń i nie zmieniają sensora ostatniego SMS-a |
| Dzienny limit SMS | maksymalna liczba części SMS na dzień (0 = bez limitu); wysyłka ponad limit kończy się błędem zamiast rachunkiem |
| Wysyłaj bez polskich znaków | `zażółć` → `zazolc`; każdy znak zajmuje wtedy jeden z 64 bajtów |
| Wysyłaj z karty SIM (ICCID) | puste = aktywna karta |

## Encje i akcje

| | |
|---|---|
| `notify.<nazwa>_sms` | wysyła do domyślnych odbiorców z opcji |
| `event.<nazwa>_sms_received` | zdarzenie `received` z `from`, `text`, `timestamp`, `iccid`, `trusted` |
| `sensor.<nazwa>_last_sms` | treść najnowszego SMS-a (stan ucięty do 255 znaków, pełna treść w `text`), przetrwa restart |
| `sensor.<nazwa>_sms_sent_today`, `..._sms_sent_this_month` | wysłane części SMS, pod rachunek operatora |
| `binary_sensor.<nazwa>_modem_connection` | połączenie SSH; host, port, użytkownik, odcisk klucza hosta (diagnostyczny) |
| `sensor.<nazwa>_receive_hook` | `active`, `anchor_missing` lub `failed` (diagnostyczny) |
| `sensor.<nazwa>_active_sim` | operator aktywnej karty SIM (diagnostyczny) |
| `unifi_sms.send` | `to` (numer lub lista), `message`; zwraca liczbę części |
| zdarzenie `unifi_sms_received` | te same dane co encja zdarzeń, do automatyzacji |

```yaml
action: unifi_sms.send
data:
  to: "+48123456789"
  message: "Brama garażowa otwarta od 10 minut"
```

```yaml
triggers:
  - trigger: event
    event_type: unifi_sms_received
    event_data:
      trusted: true
actions:
  - action: persistent_notification.create
    data:
      message: "{{ trigger.event.data.text }}"
```

## Znane ograniczenia

- **64 bajty na SMS** przy wysyłce (firmware). Dłuższe teksty wychodzą jako kilka
  wiadomości. Polska litera zajmuje 2 bajty; opcja wysyłki bez polskich znaków to
  omija.
- **Przychodzący tekst o długości podzielnej przez 8 traci ostatni znak**
  (firmware 7.5.3, wewnątrz `uiwwand`). `12345678` dochodzi jako `1234567`. W
  komendach SMS unikaj takich długości albo kończ komendę spacją lub kropką.
- Wiadomości, które przyjdą między restartem modemu a ponownym połączeniem Home
  Assistant, nie trafiają do kolejki.
- **Jedna instancja Home Assistant na modem.** Kolejka odbioru jest wspólna, więc dwie
  instancje połączone z tym samym modemem dostawałyby po części wiadomości.
- Aktualizacja firmware może zmienić skrypt zdarzeń. Jeśli hooka nie da się wpiąć,
  integracja zapisuje ostrzeżenie w logu i dalej wysyła; odbiór stoi do czasu
  poprawki.

## Rozwój

```sh
pip install pytest pytest-homeassistant-custom-component "asyncssh>=2.21.0" ruff
pytest -q
ruff check .
```

## Licencja

MIT
