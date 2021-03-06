'''
 * @Author: Yizhe Zhang 
 * @Date: 2019-04-02 13:46:04 
 * @Last Modified by:   Yizhe Zhang 
 * @Last Modified time: 2019-04-02 13:46:04 
 '''
import sys
import torch
import tqdm
import logging
# import nltk

import numpy as np

from pycocoevalcap.bleu.bleu import Bleu
from collections import OrderedDict
from pycocoevalcap.rouge.rouge import Rouge
from pdb import set_trace as bp
from collections import defaultdict

from gpt2_training.generation_auto import generate_sequence

from pytorch_pretrained_bert import GPT2Tokenizer

logger = logging.getLogger(__name__)


EOS_ID = 50256


def cal_BLEU_4(generated, reference, is_corpus = False):
    #print 'in BLEU score calculation'
    #the maximum is bigram, so assign the weight into 2 half.
    BLEUscore = [0.0,0.0,0.0,0.0]
    for idx, g in enumerate(generated):
        if is_corpus:
            score, scores = Bleu(4).compute_score(reference, {0: [g]})
        else:
            score, scores = Bleu(4).compute_score({0: [reference[0][idx]]} , {0: [g]})
        #print g, score
        for i, s in zip([0,1,2,3],score):
            BLEUscore[i]+=s
        #BLEUscore += nltk.translate.bleu_score.sentence_bleu(reference, g, weight)
    BLEUscore[0] = BLEUscore[0]/len(generated)
    BLEUscore[1] = BLEUscore[1]/len(generated)
    BLEUscore[2] = BLEUscore[2]/len(generated)
    BLEUscore[3] = BLEUscore[3]/len(generated)
    return BLEUscore


def cal_entropy(generated):
    #print 'in BLEU score calculation'
    #the maximum is bigram, so assign the weight into 2 half.
    etp_score = [0.0,0.0,0.0,0.0]
    div_score = [0.0,0.0,0.0,0.0]
    counter = [defaultdict(int),defaultdict(int),defaultdict(int),defaultdict(int)]
    for gg in generated:
        g = gg.rstrip().split()
        for n in range(4):
            for idx in range(len(g)-n):
                ngram = ' '.join(g[idx:idx+n+1])
                counter[n][ngram] += 1
    for n in range(4):
        total = sum(counter[n].values()) +1e-10
        for v in counter[n].values():
            etp_score[n] += - (v+0.0) /total * (np.log(v+0.0) - np.log(total))
        div_score[n] = (len(counter[n].values())+0.0) /total
    return etp_score, div_score 
 
def prepare_for_bleu(sentence):
    sent=[]
    for s in sentence[1:]:
        if s != EOS_ID:
            sent.append(s)
        else:
            break
    # sent.append(EOS_ID)
    # while len(sent)<2:
    #     sent.append(EOS_ID)
    #sent = ' '.join([ixtoword[x] for x in sent])
    #sent = ' '.join([str(x) for x in sent])
    return sent


def eval_model_generation(model_bert, model_gpt, model_pre, tokenizer, eval_dataloader, epoch_id, args):
    model_bert.eval()
    model_gpt.eval()
    model_pre.eval()
    outs = []
    targets = []
    with torch.no_grad():
        # with tqdm.tqdm(total=len(eval_dataloader), desc=f"Epoch {epoch_id-1} dev set") as pbar:
        # for step, batch in enumerate(tqdm.tqdm(eval_dataloader, desc="Iteration")):
        for step, batch in enumerate(eval_dataloader):
            batch = tuple(t.to(args.device) for t in batch)
            input_ids_bert, input_ids_gpt, lm_labels = batch
                # print(input_ids.shape, position_ids.shape, token_ids.shape, label_ids.shape)
                # import pdb; pdb.set_trace()

            encoded_layers, _ = model_bert(input_ids_bert, torch.zeros_like(input_ids_bert), 1 - (torch.zeros_like(input_ids_bert) == input_ids_bert), False)
            history = encoded_layers[:, 0, :].unsqueeze(1)  # .half()
            context = model_pre(input_ids=None, position_ids=None, token_type_ids=None, lm_labels=None, past=None, history=history)

            out = generate_sequence(model_gpt, input_ids_bert.size(0), length=args.max_seq_length, temperature=args.temperature, top_k=args.top_k, sample=args.is_sampling, past=context)

            out = out.tolist()
            outs.extend(out)
            target = [[x for x in l if x != -1] for l in lm_labels.cpu().numpy()]
            targets.extend(target)
            if step == 99:
                break

        val_set = [tokenizer.decode(prepare_for_bleu(s)) for s in targets]
        gen = [tokenizer.decode(prepare_for_bleu(s)) for s in outs]
            # embedding = res['emb']
            # embedding = {i:np.array(embedding[i]) for i in range(len(embedding))}
        [bleu1s, bleu2s, bleu3s, bleu4s] = cal_BLEU_4(gen, {0: val_set}, is_corpus = False)
            # [rouge1,rouge2,rouge3,rouge4,rougeL,rouges] = cal_ROUGE(gen, {0: val_set}, is_corpus = opt.is_corpus)
        etp_score, dist_score = cal_entropy(gen)
            #bleu_nltk = cal_BLEU_4_nltk(gen, val_set, is_corpus = opt.is_corpus)
            # rel_score = cal_relevance(gen, val_set, embedding)

            # print(f"\n Epoch {epoch}: Val loss {np.mean(loss)} Val ppl {np.mean(ppl)} ")
        print("=" * 80)
        print('Val BLEU: ' + ' '.join([str(round(it,3)) for it in (bleu1s, bleu2s, bleu3s, bleu4s)]))
            # print 'Val Rouge: ' + ' '.join([str(round(it,3)) for it in (rouge1,rouge2,rouge3,rouge4)])
        print('Val Entropy: ' + ' '.join([str(round(it,3)) for it in (etp_score[0],etp_score[1],etp_score[2],etp_score[3])]))
        print('Val Diversity: ' + ' '.join([str(round(it,3)) for it in (dist_score[0],dist_score[1],dist_score[2],dist_score[3])]))
            # print 'Val (G,A,E): ' + ' '.join([str(round(it,3)) for it in (rel_score[0],rel_score[1],rel_score[2])])
            # print 'Val Avg. length: ' + str(round(np.mean([len([y for y in x if y!=0]) for x in res_all]),3))
        for n_s in range(args.nsamples):
            print("=" * 40 + " SAMPLE " + str(n_s) + "=" * 40)
            gt = val_set[-1-n_s]
            resp = gen[-1-n_s]
            print(f"Original: \t {gt} \n Reproduced: \t {resp}\n")
        print("=" * 80)

        sys.stdout.flush()
        torch.cuda.empty_cache()
        return gen



def eval_model_loss(model_bert, model_gpt, model_pre, eval_dataloader, epoch_id, args):
    # use the same signature with eval_model_generation
    # logger.info('compute eval model loss, using eval mode, please change it back to train after calling this function')
    model_bert.eval()
    model_gpt.eval()
    model_pre.eval()
    tot_loss = []
    tot_ppl = []
    tot_sample = []
    tot_correct = 0
    n_token_real = 0
    with torch.no_grad():
        for step, batch in enumerate(eval_dataloader):
            batch = tuple(t.to(args.device) for t in batch)
            input_ids_bert, input_ids_gpt, lm_labels = batch
            n_sample = input_ids_bert.shape[0]

            encoded_layers, _ = model_bert(input_ids_bert, torch.zeros_like(input_ids_bert), 1 - (torch.zeros_like(input_ids_bert) == input_ids_bert), False)
            history = encoded_layers[:, 0, :].unsqueeze(1)#.half()
            context = model_pre(input_ids=None, position_ids=None, token_type_ids=None, lm_labels=None, past=None, history=history)
            # position_ids = torch.tensor(range(input_ids_gpt.size(-1))).repeat([args.train_batch_size, 1]).cuda()
            # token_ids = torch.zeros([args.train_batch_size, input_ids_gpt.size(-1)], dtype = torch.long).cuda()

            loss, ppl, correct, total, _= model_gpt(input_ids=input_ids_gpt, position_ids=None, token_type_ids=None, lm_labels=lm_labels, past=context, history=None)

            if args.n_gpu > 0:
                tot_loss.append(loss.mean().item() * n_sample)
                if ppl.mean().item() < 1000:
                    tot_ppl.append(ppl.mean().item() * n_sample)
                else:
                    tot_ppl.append(1000 * n_sample)
                tot_correct = tot_correct + correct
                n_token_real = n_token_real + total
            else:
                tot_loss.append(loss.item() * n_sample)
                tot_ppl.append(ppl.item() * n_sample)
            tot_sample.append(n_sample)
            if step == 99:
                break
    print(f"\n Epoch {epoch_id}: Val loss {np.sum(tot_loss) / np.sum(tot_sample)} Val ppl {np.sum(tot_ppl) / np.sum(tot_sample)} Val correct {tot_correct/n_token_real}")
    return np.sum(tot_loss) / np.sum(tot_sample), np.sum(tot_ppl) / np.sum(tot_sample), tot_correct/n_token_real
