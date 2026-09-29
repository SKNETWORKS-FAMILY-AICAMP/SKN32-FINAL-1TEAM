# -*- coding: utf-8 -*-
"""리랭커 학습 (딥러닝). GPU 로 돌린다.

  python ml/04_reranker_train.py --plan          받을 것·건수만 확인
  python ml/04_reranker_train.py                 학습
  python ml/04_reranker_train.py --epochs 6

왜 스크립트인가. 학습은 노트북 커널이 끊기면 날아간다. 그래서 학습만 스크립트로
빼고, 결과를 보는 일은 05_reranker_report.ipynb 가 한다.

무엇을 가르치나. 질의 한 줄과 공고 한 줄을 **붙여서 같이 읽고** 0~1 점수를 내게
한다. 정답은 관련도 2=1.0 · 1=0.5 · 0=0.0 이다.

왜 LoRA 인가. 학습 데이터가 893쌍뿐이다. 5억 개가 넘는 모델 전체를 고치면
데이터를 외워버려서(과적합) 처음 보는 질의에 약해진다. LoRA 는 모델을 얼려두고
아주 작은 부품만 학습한다. 메모리도 훨씬 덜 쓴다(12GB 에서 넉넉하다).
"""
import argparse
import io
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import rerank_common as rc

SEED = 20260916


def say(*a):
    print(*a, flush=True)


def set_seed(seed):
    import numpy as np
    import torch
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--epochs', type=int, default=4, help='몇 바퀴 돌릴지 (기본 4)')
    ap.add_argument('--batch', type=int, default=4, help='한 번에 볼 쌍 수. 메모리 부족하면 줄인다')
    ap.add_argument('--accum', type=int, default=2, help='이만큼 모아서 한 번 반영 (batch 와 곱해 실효 크기)')
    ap.add_argument('--lr', type=float, default=2e-4, help='학습률. LoRA 는 전체 학습보다 크게 준다')
    ap.add_argument('--rank', type=int, default=16, help='LoRA 부품 크기')
    ap.add_argument('--out', default=rc.ADAPTER_DIR)
    ap.add_argument('--plan', action='store_true', help='건수만 확인하고 끝낸다')
    args = ap.parse_args()

    say('학습 데이터를 모은다 (EC2 MySQL 에서 공고를 읽는다)')
    train = rc.load_pairs('train')
    test = rc.load_pairs('test')
    say('  학습 %d쌍 · 시험 %d쌍' % (len(train), len(test)))
    dist = {}
    for pair in train:
        label = pair[2]
        dist[label] = dist.get(label, 0) + 1
    say('  정답 분포 : ' + ' · '.join('%.1f→%d건' % (k, v) for k, v in sorted(dist.items())))

    if args.plan:
        say('')
        say('--plan 이라 여기서 멈춘다. 실제 학습은 --plan 없이 실행한다.')
        say('처음 실행하면 모델 %s 를 내려받는다 (약 2.2GB).' % rc.MODEL_NAME)
        return

    import torch
    from torch.utils.data import DataLoader, Dataset
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    from peft import LoraConfig, get_peft_model

    if not torch.cuda.is_available():
        say('')
        say('⚠ GPU 를 못 찾았다. CPU 로도 돌지만 몇 시간이 걸린다.')
        say('  torch 가 CPU 판인지 확인한다 : python -c "import torch; print(torch.__version__)"')
        say('  +cpu 로 끝나면 CUDA 판으로 다시 깐다.')
        if input('  그래도 계속할까? [y/N] ').strip().lower() != 'y':
            return

    set_seed(SEED)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    say('장치 : %s' % (torch.cuda.get_device_name(0) if device == 'cuda' else 'CPU'))

    tokenizer = AutoTokenizer.from_pretrained(rc.MODEL_NAME)
    model = AutoModelForSequenceClassification.from_pretrained(rc.MODEL_NAME, num_labels=1)

    # 모델 전체를 얼리고 attention 의 작은 부품만 학습한다
    lora = LoraConfig(
        r=args.rank, lora_alpha=args.rank * 2, lora_dropout=0.1,
        target_modules=['query', 'key', 'value'],
        task_type='SEQ_CLS',
    )
    model = get_peft_model(model, lora)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    say('학습할 부품 : %s개 / 전체 %s개 (%.2f%%)'
        % (f'{trainable:,}', f'{total:,}', trainable / total * 100))
    model = model.to(device)

    class Pairs(Dataset):
        def __init__(self, rows):
            self.rows = rows

        def __len__(self):
            return len(self.rows)

        def __getitem__(self, i):
            q, n, lab, _qid, _nid = self.rows[i]
            return q, n, lab

    def collate(batch):
        qs, ns, labs = zip(*batch)
        enc = tokenizer(list(qs), list(ns), padding=True, truncation=True,
                        max_length=rc.MAX_LEN, return_tensors='pt')
        enc['labels'] = torch.tensor(labs, dtype=torch.float32)
        return enc

    loader = DataLoader(Pairs(train), batch_size=args.batch, shuffle=True,
                        collate_fn=collate, drop_last=False)
    test_loader = DataLoader(Pairs(test), batch_size=args.batch * 2, shuffle=False,
                             collate_fn=collate)

    optim = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=args.lr)
    steps = (len(loader) // args.accum + 1) * args.epochs
    sched = torch.optim.lr_scheduler.OneCycleLR(optim, max_lr=args.lr, total_steps=max(steps, 1),
                                                pct_start=0.1)
    loss_fn = torch.nn.BCEWithLogitsLoss()
    use_bf16 = device == 'cuda' and torch.cuda.is_bf16_supported()
    say('혼합정밀도 : %s' % ('bf16' if use_bf16 else '끔'))

    def evaluate_loss():
        model.eval()
        total_loss, n = 0.0, 0
        with torch.no_grad():
            for batch in test_loader:
                labels = batch.pop('labels').to(device)
                batch = {k: v.to(device) for k, v in batch.items()}
                with torch.autocast('cuda', dtype=torch.bfloat16, enabled=use_bf16):
                    logits = model(**batch).logits.view(-1).float()
                total_loss += loss_fn(logits, labels).item() * len(labels)
                n += len(labels)
        model.train()
        return total_loss / max(n, 1)

    say('')
    say('%-6s %-12s %-12s %-10s %s' % ('바퀴', '학습 손실', '시험 손실', '걸린 시간', ''))
    say('-' * 56)
    history = []
    best = {'epoch': None, 'test_loss': float('inf')}
    os.makedirs(args.out, exist_ok=True)
    model.train()
    for epoch in range(1, args.epochs + 1):
        t0 = time.time()
        running, seen = 0.0, 0
        optim.zero_grad(set_to_none=True)
        for step, batch in enumerate(loader, 1):
            labels = batch.pop('labels').to(device)
            batch = {k: v.to(device) for k, v in batch.items()}
            try:
                with torch.autocast('cuda', dtype=torch.bfloat16, enabled=use_bf16):
                    logits = model(**batch).logits.view(-1).float()
                loss = loss_fn(logits, labels) / args.accum
                loss.backward()
            except torch.cuda.OutOfMemoryError:
                say('')
                say('⚠ GPU 메모리가 모자란다. --batch 를 줄여서 다시 해본다.')
                say('   예: python ml/04_reranker_train.py --batch 2 --accum 4')
                raise
            running += loss.item() * args.accum * len(labels)
            seen += len(labels)
            if step % args.accum == 0 or step == len(loader):
                torch.nn.utils.clip_grad_norm_(
                    [p for p in model.parameters() if p.requires_grad], 1.0)
                optim.step()
                sched.step()
                optim.zero_grad(set_to_none=True)
        tr = running / max(seen, 1)
        te = evaluate_loss()
        history.append({'epoch': epoch, 'train_loss': tr, 'test_loss': te})

        # 시험 손실이 가장 낮았던 바퀴를 저장한다. 마지막 바퀴가 최선이 아니다 —
        # 데이터가 893쌍뿐이라 몇 바퀴 지나면 외우기 시작(과적합)한다.
        mark = ''
        if te < best['test_loss']:
            best = {'epoch': epoch, 'test_loss': te}
            # 토크나이저는 저장하지 않는다. 원본 모델에서 그대로 받아 쓰므로
            # 사본일 뿐인데 tokenizer.json 이 100만 줄(17MB)이라 저장소를 키운다.
            # 불러올 때는 rerank_common.Scorer 가 MODEL_NAME 에서 가져온다.
            model.save_pretrained(args.out)
            mark = '← 지금까지 최선. 저장함'
        say('%-6d %-12.4f %-12.4f %-10s %s' % (epoch, tr, te, '%.0f초' % (time.time() - t0), mark))

    say('')
    say('가장 좋았던 바퀴 : %d (시험 손실 %.4f)' % (best['epoch'], best['test_loss']))
    if best['epoch'] < args.epochs:
        say('그 뒤로는 나빠졌다 — 외우기 시작한 것이다. 저장된 것은 %d바퀴 모델이다.'
            % best['epoch'])

    json.dump({
        'base_model': rc.MODEL_NAME,
        'method': 'LoRA',
        'seed': SEED,
        'epochs': args.epochs,
        'batch': args.batch,
        'accum': args.accum,
        'effective_batch': args.batch * args.accum,
        'lr': args.lr,
        'lora_rank': args.rank,
        'max_len': rc.MAX_LEN,
        'train_pairs': len(train),
        'test_pairs': len(test),
        'trainable_params': trainable,
        'total_params': total,
        'best_epoch': best['epoch'],
        'best_test_loss': best['test_loss'],
        'history': history,
    }, io.open(os.path.join(args.out, 'train_info.json'), 'w', encoding='utf-8'),
        ensure_ascii=False, indent=1)

    say('')
    say('저장 → %s' % args.out)
    say('다음 : 05_reranker_report.ipynb 에서 검색 성능을 잰다.')


if __name__ == '__main__':
    main()
