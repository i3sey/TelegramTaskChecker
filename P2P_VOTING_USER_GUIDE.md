# P2P Review & Voting System - User Guide

## 📚 Overview

This system has two main features for students:

1. **P2P Review** (Peer-to-Peer Review)
   - Review other students' submissions
   - Give scores and comments
   - Fairness ensured: all submissions get equal reviews

2. **Voting** (Collective Decision-Making)
   - Vote on submissions
   - Like submissions or give scores
   - See which ones are most popular

---

## 👥 P2P Review (Peer-to-Peer)

### What is P2P Review?

P2P means **students review each other's work**. Instead of just experts grading, all students participate in evaluating submissions.

### Requirements

✅ You must be registered as a **STUDENT**
✅ You must have **submitted your own work** in the campaign
✅ The **campaign must be active** (not closed)
✅ You **cannot review your own work**

### How to Use P2P Review

#### Step 1: Start Review
```
/p2p
or
Press button: 👥 Проверить работы
```

You'll see a list of P2P campaigns with your progress:
```
👥 Выберите кампанию для P2P-проверки:

📋 Campaign 1 (2/5)   ← You've completed 2 of 5 required reviews
📋 Campaign 2 (0/3)   ← You haven't started this one yet
```

#### Step 2: Select Campaign

Click on a campaign you want to review for.
- System checks: Have you completed the required reviews? (if yes → "All done!")
- System loads: Next submission that needs review

#### Step 3: Review the Submission

You'll see:
```
🧑‍🤝‍🧑 P2P-проверка

📋 Кампания: Campaign Name
🆔 Работа: 12345
⏳ Время на проверку: 48 часов

Оценивание: от 0 до 100
```

Then you get the actual file/work to review.

#### Step 4: Enter Score

```
⬇️ Введите оценку числом (0–100).
```

Type your score. Example:
```
85
```

System validates:
- ✅ Score is in allowed range
- ❌ Score too low/high → error, try again

#### Step 5: Enter Comment (Optional)

```
📝 Оценка сохранена: 85

Теперь отправьте текстовый комментарий к работе.
Если комментарий не нужен, нажмите кнопку ниже.

[✅ Отправить без комментария]
[↩️ Вернуть работу в очередь]
```

You can:
- Send text comment
- Skip comment
- Cancel review (work goes back to queue)

#### Step 6: Confirm

```
💬 Комментарий сохранён.

Текст: "Great work, but check grammar!"

Нажмите «Подтвердить», чтобы завершить проверку.

[✅ Подтвердить] [↩️ Вернуть в очередь]
```

Review your comment, then confirm or cancel.

#### Step 7: See Results

```
✅ Рецензия сохранена!

🆔 Работа: 12345
⭐ Оценка: 85
💬 Комментарий: Great work, but check grammar!

📈 Ваш прогресс: 3/5
📊 Эта работа получила все рецензии!

[▶️ Проверить следующую]
```

You see:
- Your score and comment
- Your progress (3 out of 5 reviews done)
- How many reviews this work has now
- Option to review next submission

### Rules & Restrictions

❌ **Cannot do:**
- Review your own work
- Review the same work twice
- Review after campaign deadline
- Change your review after submission

✅ **Can do:**
- Skip to next submission (don't vote on some)
- Review multiple submissions
- Add detailed comments
- See your progress in real-time

### Progress Tracking

```
/p2p
👥 Выберите кампанию для P2P-проверки:

📋 Campaign 1 (2/5)   ← Number means: done/required
   ✅ You've completed 2
   🔄 3 more to go
   
📋 Campaign 2 (0/3)
   ⭕ You haven't started yet
   🔄 Need to do 3
```

When you complete all required reviews:
```
🎉 Поздравляем!

Вы выполнили все требуемые рецензии для этой кампании.
```

---

## 🗳️ Voting

### What is Voting?

Voting is a **lighter** form of feedback where you simply indicate if you like/dislike submissions or give them a rating.

### Two Types of Voting

#### Type 1: Like Voting (Simple)
```
Just click 👍 or ⏭️
```

#### Type 2: Score Voting (Rating)
```
⬇️ Введите оценку числом (0–100).
```

### How to Use Voting

#### Step 1: Start Voting
```
/vote
or
Press button: 🗳 Голосование
```

See available voting campaigns:
```
🗳 Выберите кампанию для голосования:

📋 Campaign A (Like)       ← Simple thumbs up
📋 Campaign B (Score)      ← Rate 0-100
```

#### Step 2: Select Campaign

Click on campaign → system loads first submission

#### Step 3: Vote

**If Like-type:**
```
🗳 Голосование

📋 Кампания: Campaign A
🆔 Работа: 54321
Тип: Like

[👍 Голосовать] [⏭ Пропустить]
```

**If Score-type:**
```
🗳 Голосование

📋 Кампания: Campaign B
🆔 Работа: 54321
Тип: Score

⬇️ Введите оценку числом (0–100).
```

#### Step 4: See Results

```
✅ Голос учтён!

Ваша оценка была сохранена.

[▶️ Следующая работа]
```

Then you can:
- Vote on next submission
- Skip to next submission  
- Exit (any time)

### Voting Rules

❌ **Cannot:**
- Vote for your own work
- Vote twice for same submission
- Change your vote

✅ **Can:**
- Skip submissions (vote_skip)
- Vote on multiple submissions
- Vote multiple campaigns

---

## 🎯 Quick Reference

### Commands
```
/p2p    → Start P2P review
/vote   → Start voting
/help   → Get help
/status → Check submission status
```

### Buttons
```
👥 Проверить работы     → P2P review
🗳 Голосование           → Voting
📊 Статус               → Check status
⋯ Ещё                   → More options
```

### Common Scenarios

**Scenario 1: I want to review other students' work**
```
1. /p2p
2. Choose campaign
3. Enter score + comment
4. Confirm
5. See progress
6. (Optional) Review next
```

**Scenario 2: I want to vote on submissions**
```
1. /vote
2. Choose campaign
3. Click Like or Enter Score
4. (Optional) Vote next
```

**Scenario 3: I forgot what I reviewed**
```
1. /status → See your latest submission
2. Or check the notifications you got
3. Or contact organizer
```

---

## ⚠️ Common Issues

### "❌ Вы не зарегистрированы"

**Problem**: You're not registered in the system

**Solution**: 
```
1. /start
2. Enter your full name
3. Choose your role
4. Select your group
```

### "⛔ Эта команда доступна только студентам"

**Problem**: You're not a student role

**Solution**:
```
1. Go to /role
2. Choose STUDENT role
3. Try again
```

### "✅ Вы уже проверяли эту работу"

**Problem**: You already reviewed this submission

**Solution**:
- You can't change your review
- Just move on to next submission
- Click "Next" button

### "📭 Нет доступных работ для проверки"

**Problem**: No more submissions to review (all done!)

**Solutions**:
- Come back later (more students might submit)
- Choose different campaign
- If you're done with required: ✅ All complete!

### "🚫 У вас уже есть работа на проверке"

**Problem**: You started reviewing but didn't finish

**Solution**:
- Continue with that work
- Or click "Cancel review" button to start over

---

## 💡 Tips & Best Practices

### For P2P Reviewers

1. **Be Fair**
   - Review consistently
   - Use full score range (0-100)
   - Don't always give 100%

2. **Give Helpful Comments**
   - Explain your score
   - Point out strengths
   - Suggest improvements

3. **Be Objective**
   - Focus on the work, not the person
   - Use rubric/criteria if provided
   - Don't let personal preference bias you

4. **Be Timely**
   - Review when campaign is open
   - Don't wait until deadline

5. **Complete Your Reviews**
   - Finish all required reviews
   - Don't just skip everything

### For Voters

1. **Vote Honestly**
   - Vote your opinion
   - Don't copy others

2. **Vote Consistently**
   - Use same scale for all
   - Think about what each score means

3. **Don't Skip Everything**
   - Skipping is OK for some
   - But vote on most submissions

---

## 🔒 Privacy & Fairness

### Anonymity (if campaign setting)
- Your name might be hidden
- Reviewers might be anonymous
- Ensures fair evaluation

### Fair Distribution
- System ensures all submissions get reviewed
- Reviews distributed evenly
- No reviewer burden unfair

### No Duplicates
- You can't review same work twice
- System prevents accidents
- Fair to author

---

## 📞 Getting Help

If you have questions:
1. Use `/help` command
2. Ask your instructor
3. Check notification messages
4. Review earlier work (if you reviewed it)

---

## 📊 System Status

Campaign Status Indicators:
```
🟢 Active       → You can review now
🟡 Coming Soon  → Review opens later  
🔴 Closed       → Review ended, no more reviews accepted
```

Your Progress:
```
⭕ (0/5)        → Haven't started
🔄 (2/5)        → In progress
✅ (5/5)        → Complete
```

---

Last Updated: May 12, 2026

For more technical details, see the architecture documentation.

