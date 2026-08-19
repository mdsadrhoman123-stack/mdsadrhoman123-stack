# GitHub প্রোফাইল কার্ড — সম্পূর্ণ বাংলা গাইড

## ১. এটা আসলে কী? বানানো কি সম্ভব?

হ্যাঁ, সম্পূর্ণ সম্ভব — এবং যা দেখছেন সেটা কোনো স্ক্রিনশট বা ছবি (PNG/JPG) নয়।

ওটা একটা **SVG ফাইল**। SVG হলো টেক্সট-ভিত্তিক ছবি, অর্থাৎ ভেতরে শুধু কিছু `<text>` ট্যাগ
আর রং লেখা থাকে। তাই এক লাইন টেক্সট বদলে দিলেই "ছবিটা" বদলে যায়।

কাজ করার পদ্ধতি তিন ধাপে:

1. একটা **Python স্ক্রিপ্ট** GitHub API-তে রিকোয়েস্ট পাঠিয়ে আপনার লাইভ ডেটা আনে
   (repo সংখ্যা, star, follower, commit, কত লাইন কোড লিখেছেন)।
2. স্ক্রিপ্টটি ওই ডেটা + আপনার অ্যাভাটার থেকে বানানো **ASCII art** বসিয়ে
   `dark_mode.svg` আর `light_mode.svg` ফাইল লিখে ফেলে (দেখতে neofetch টার্মিনালের মতো)।
3. একটা **GitHub Actions workflow** প্রতিদিন নির্দিষ্ট সময়ে স্ক্রিপ্টটি চালিয়ে
   নতুন SVG কমিট করে দেয়। README-তে শুধু ওই SVG দেখানো হয়, তাই প্রোফাইল
   প্রতিদিন নিজে থেকেই আপডেট হয়। (Reddit-এর ওই ব্যক্তি ঠিক এটাই বলেছেন:
   *"it is just svg ... i update it by making http requests from github ... at 11 am"*)

মূল আইডিয়াটি জনপ্রিয় হয়েছে `Andrew6rant/Andrew6rant` রিপো থেকে — আপনার প্রথম
স্ক্রিনশটটি (andrew@grant) আসলে ওটাই।

---

## ২. এই ফোল্ডারে কী কী আছে

| ফাইল | কাজ |
|---|---|
| `config.yml` | **শুধু এই ফাইলটাই এডিট করবেন** — নাম, OS, ভাষা, শখ, contact, রং |
| `generate.py` | GitHub থেকে ডেটা এনে SVG দুটো বানায় |
| `.github/workflows/update-card.yml` | প্রতিদিন অটো-আপডেটের ব্যবস্থা |
| `requirements.txt` | দরকারি Python লাইব্রেরি |
| `README.md` | প্রোফাইলে যা দেখা যাবে (dark/light অটো সুইচ) |

---

## ৩. সেটআপ (ধাপে ধাপে)

### ধাপ ১ — Special repository বানান

GitHub-এ নতুন repository খুলুন, নাম দিতে হবে **হুবহু আপনার username**:

```
mdsadrhoman123-stack/mdsadrhoman123-stack
```

Public রাখুন এবং "Add a README file" টিক দিন। এই বিশেষ রিপোর README-ই
আপনার প্রোফাইল পেজে দেখায়।

### ধাপ ২ — ফাইলগুলো রিপোতে দিন

```bash
git clone https://github.com/mdsadrhoman123-stack/mdsadrhoman123-stack.git
cd mdsadrhoman123-stack
# এই ফোল্ডারের সব ফাইল এখানে কপি করুন
git add .
git commit -m "feat: neofetch style profile card"
git push
```

### ধাপ ৩ — `config.yml` নিজের মতো করে সাজান

```yaml
username: mdsadrhoman123-stack
title: sayad@automation             # কার্ডের হেডিং
birthday: "2005-01-15"     # Uptime এখান থেকে হিসাব হয়
sections:
  - name: Contact
    items:
      - [Email.Personal, "mdsadrhoman123@gmail.com"]
```

`{repos}`, `{stars}`, `{commits}`, `{followers}`, `{loc}`, `{uptime}` —
এই প্লেসহোল্ডারগুলো অটোমেটিক আসল সংখ্যা দিয়ে বদলে যায়।

### ধাপ ৪ — টোকেন (LOC/commit গোনার জন্য দরকার)

GitHub → Settings → Developer settings → **Personal access tokens (classic)** →
Generate new token → scope: `repo`, `read:user` → টোকেন কপি করুন।

এরপর আপনার রিপোতে: Settings → Secrets and variables → Actions → New secret
নাম দিন `PROFILE_TOKEN`, ভ্যালুতে টোকেনটা পেস্ট করুন।

> টোকেন না দিলেও চলবে, তবে তখন `SKIP_LOC=1` মোডে কম ডেটা আসবে।

### ধাপ ৫ — Actions চালু করুন

রিপোর **Actions** ট্যাবে যান → workflow enable করুন → "Update profile card" →
**Run workflow** চাপুন। এক-দুই মিনিটে `dark_mode.svg` তৈরি হয়ে যাবে,
আর প্রোফাইলে কার্ড দেখা যাবে।

এরপর থেকে প্রতিদিন **বাংলাদেশ সময় সকাল ১১:৩০**-এ নিজে থেকেই আপডেট হবে
(সময় বদলাতে চাইলে workflow ফাইলের `cron: "30 5 * * *"` লাইনটা বদলান — ওটা UTC)।

---

## ৪. নিজের কম্পিউটারে টেস্ট করা

```bash
pip install -r requirements.txt
GITHUB_TOKEN=আপনার_টোকেন python3 generate.py
# দ্রুত টেস্ট (LOC গণনা বাদ দিয়ে):
SKIP_LOC=1 GITHUB_TOKEN=আপনার_টোকেন python3 generate.py
```

---

## ৫. "Uptime" ফিল্ডে কী লিখবেন — কিছু আইডিয়া

`Uptime` আসলে neofetch-এর মজা — কম্পিউটার কত সময় ধরে চালু আছে, সেটার জায়গায়
মানুষ নিজের "চালু থাকার সময়" লেখে। আপনার জন্য কয়েকটা অপশন:

1. **বয়স (অটো)** — `21 years, 7 months, 20 days` (জন্মতারিখ দিলে নিজেই হিসাব হয়)
2. **দুই লাইনে ভাগ** (রেফারেন্সে শুধু `Uptime` আছে; চাইলে নিচের লাইনটা যোগ করুন):
   ```
   Uptime:              21 years, 7 months, 20 days
   Uptime.Automation:   2 years, 0 unplanned downtime
   ```
3. **টেক-জোকস স্টাইল** — যেকোনো একটা বেছে নিন:
   - `2 years in automation - 99.9% SLA`
   - `2 years since first n8n workflow`
   - `2 years, 20+ systems, 0 rollbacks`
   - `21 years (human), 2 years (automation runtime)`
   - `booted 2005, running automations since 2024`
4. **Load average স্টাইল** (বাড়তি মজার লাইন যোগ করতে চাইলে):
   ```
   - [Load average, "3 client projects, 2 side builds"]
   - [Memory, "20+ shipped systems / unlimited coffee"]
   ```

আমার পরামর্শ: বয়স অটো রাখুন, আর নিচে `Uptime.Automation`-এ অভিজ্ঞতা দেখান —
রিক্রুটার/ক্লায়েন্ট দুটোই এক নজরে বুঝে যাবে।

---

## ৬. টুকিটাকি টিপস

- **ছবি বদলাতে** রিপোর `portrait.png` ফাইলটা নিজের ছবি দিয়ে রিপ্লেস করুন
  (অথবা `avatar_url`-এ লিঙ্ক দিন, খালি রাখলে GitHub প্রোফাইল ছবি নেবে)।
  **সবচেয়ে ভালো রেজাল্ট:** বড় (৫০০px+), এক রঙের ব্যাকগ্রাউন্ডওয়ালা, বুক পর্যন্ত
  ক্রপ করা ছবি (PNG হলে ব্যাকগ্রাউন্ড ট্রান্সপারেন্ট হলে সবচেয়ে পরিষ্কার আসবে)।
- **ASCII art টিউন করার নব:** `ascii_width` (৪০–৬০), `char_ratio` (0.45–0.60),
  `remove_background` (true/false), `background_tolerance` (৮–২৫), `invert_ascii`।
  প্রতিবার চালালে `ascii_preview.txt`-এ আর্টটা ডাম্প হয় — চাইলে হাতে এডিট করে
  `ascii_file: "ascii_preview.txt"` সেট করে দিতে পারেন।
- **এক লাইনে দুই কলাম** (রেফারেন্সের Repos | Stars লাইনের মতো) লিখতে চার-অংশের
  আইটেম দিন: `- [Repos, "{repos}", Stars, "{stars}"]`।
- **রঙের মার্কআপ:** ভ্যালুর ভেতর `[g]...[/]` = সবুজ, `[r]...[/]` = লাল।
- **নিজের হাতে আঁকা ASCII** ব্যবহার করতে চাইলে একটা `art.txt` ফাইল বানিয়ে
  `ascii_file: "art.txt"` লিখে দিন।
- **রং বদলাতে** `config.yml`-এর `theme` অংশ এডিট করুন।
- **LOC-এর সংখ্যা প্রথমবার আনতে সময় লাগে** (প্রতিটি রিপোর কমিট পড়তে হয়);
  পরে `cache/` ফোল্ডারে জমা থাকে বলে দ্রুত হয়।
