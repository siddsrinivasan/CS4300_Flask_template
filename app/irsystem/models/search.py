import gc
import os
import sys
import json
import string
import pandas
import pickle
import numpy as np
from collections import defaultdict
from query_expansion import expand_query
from search_helper import find_coherent_set
from scipy.sparse import csr_matrix, load_npz
from sklearn.feature_extraction.text import TfidfVectorizer

reload(sys)
sys.setdefaultencoding('utf8')

########## change back for docker ###################
BASE = "app/irsystem/models"

def tokenize_query(query, ds, vocab_to_ix, words_compressed, docs_compressed, ATN_word_to_ix):
    """
    Returns a dictionary with structure {term : frequency}. Also preprocesses
    the input query string using the Sklearn TfidfVectorizer.
    """
    print >> sys.stderr, "tokenize_query"
    helper = TfidfVectorizer(min_df=3, stop_words='english',  dtype=np.int16)
    tfidf_preprocessor = helper.build_preprocessor()
    tfidf_tokenizer = helper.build_tokenizer()
    prepro_q = tfidf_preprocessor(query)
    q_tokens = tfidf_tokenizer(prepro_q)
    gc.collect()
    query_dict_ix = defaultdict(int)
    query_dict_term = defaultdict(int)
    for tok in q_tokens:
        tfidf_vocab_ix = vocab_to_ix.get(tok, -1)
        if tfidf_vocab_ix != -1:
            query_dict_ix[vocab_to_ix[tok]] += 1
            query_dict_term[tok] += 1
    print >> sys.stderr, "lending control to expand query"
    expanded_query_dict = expand_query(query_dict_ix, query_dict_term, vocab_to_ix, \
     words_compressed, docs_compressed, ATN_word_to_ix)
    gc.collect()
    return expanded_query_dict


def get_tfidf_of_query(query_dict, ds):
    """
    Create query vector
    """
    print >> sys.stderr, "get_tfidf_of_query"
    with open(os.path.join(BASE,os.path.join(ds, 'idf_vals.npy'))) as f:
        idf_vals= np.load(f)
        ix, tf = zip(*list(query_dict.items()))
        data = []
        for i, freq in zip(ix, tf):
            data.append(idf_vals[i] * freq)
        q_vec = csr_matrix((data, (np.zeros(len(ix)), ix)), shape=(1, len(idf_vals)))
        f.close()
        gc.collect()
        return q_vec.astype(dtype=np.float16)


def return_relevant_red_doc_ixs(query_vec, ds, t):
    """
    Return relevant document ids that pass threshold t
    """
    print >> sys.stderr, "return_relevant_red_doc_ixs"
    with open(os.path.join(BASE, os.path.join(ds, 'tfidf_mat.npz'))) as f:
        tfidf_mat= load_npz(f)
        cos_sim = (tfidf_mat.dot(query_vec.T)).T
        gc.collect()
        most_rel = zip(cos_sim.data, cos_sim.nonzero()[1])
        most_rel = [(val, ix) for val, ix in most_rel if val > t]
        f.close()
        gc.collect()
        return most_rel


def return_red_ixs(query, ds, t, red_vocab_to_ix, words_compressed, docs_compressed, ATN_word_to_ix):
    print >> sys.stderr, "return_red_ixs"
    tokens = tokenize_query(query, ds, red_vocab_to_ix, words_compressed, docs_compressed, ATN_word_to_ix)
    if tokens == {}:
        return []
    query_vec = get_tfidf_of_query(tokens, ds)
    rel_doc_ixs = return_relevant_red_doc_ixs(query_vec, ds, t)
    return rel_doc_ixs


def return_reu_ids(query, ds, t, f, f2, reu_vocab_to_ix, words_compressed, docs_compressed, ATN_word_to_ix):
    print >> sys.stderr, "return_reu_ids"
    tokens = tokenize_query(query, ds, reu_vocab_to_ix, words_compressed, docs_compressed, ATN_word_to_ix)
    if tokens == {}:
        return []
    query_vec = get_tfidf_of_query(tokens, ds)
    rel_doc_ixs = return_relevant_reu_doc_ids(query_vec, ds, t, f, f2)
    return rel_doc_ixs

##################################################################################################
def return_relevant_reu_doc_ids(query_vec, ds, t, f, f2):
    print >> sys.stderr, "return_relevant_reu_doc_ids NEW"

    cos_sim = (f.dot(query_vec.T)).T
    most_rel = zip(cos_sim.data, cos_sim.nonzero()[1])
    most_rel = [(val, f2[str(ix)].encode("utf8")) for val, ix in most_rel if val > t]

    return most_rel
#################################################################################################

def reu_id_decomp(reuters_ids):
    """
    Return a tuple where the first value is a
    dictionary {reuter_id: cossim score} and the
    second value is a set of all relevant reuter ids
    """
    print >> sys.stderr, "reu_id_decomp"
    d = {}
    reu_ids = set()
    for val, reu_id in reuters_ids:
        d[reu_id] = val
        reu_ids.add(reu_id)
    return (d, reu_ids)


def complete_search(query, tf_idf_npz_reu, reu_ix_to_val, id_to_reu, red_vocab_to_ix, \
 reu_vocab_to_ix, words_compressed, docs_compressed, ATN_word_to_ix, reddit_ix_to_val, date_to_id, red_text, irrel_docs=[]):
    """
    Given a user query, return large cards where
    reddit links to reuters headlines as well as
    small cards that contain reuters headlines
    (That had no reddit match)
    """
    print >> sys.stderr, "complete search start"
    reddit_ixs = return_red_ixs(query, 'reddit', 3, red_vocab_to_ix, words_compressed, docs_compressed, ATN_word_to_ix)
    reuters_ids = set(return_reu_ids(query, 'reuters', 3, tf_idf_npz_reu, reu_ix_to_val, reu_vocab_to_ix, \
        words_compressed, docs_compressed, ATN_word_to_ix))

    #Relevance bootstrap with SVD
    print >> sys.stderr, "before da pickle"
    reuters_ids, reddit_ixs = find_coherent_set(id_to_reu, red_text, reuters_ids, reddit_ixs, irrel_docs)
    red_text = None
    gc.collect()

    print >> sys.stderr, "size of set: " + str(len(reuters_ids))
    reu_id_dict, reu_id_set = reu_id_decomp(reuters_ids)
    print >> sys.stderr, "decomped"
    cards = []
    #Iterate over reddit tuples (i.e. big cards)
    for val, ix in reddit_ixs:
        tup = reddit_ix_to_val[str(ix)]

        baddate= tup[0]
        baddate= string.split(baddate, '/')
        reddate= baddate[2]
        if len(baddate[0]) == 1:
            reddate += "0" + baddate[0]
        else:
            reddate += baddate[0]
        if len(baddate[1]) == 1:
            reddate += "0" + baddate[1]
        else:
            reddate += baddate[1]

        tup_ixs = date_to_id.get(reddate.encode("utf8"), -1)
        #Reddit has date, but reuters does not
        if tup_ixs == -1:
            #print("IN -1")
            card = [reddate.encode("utf8"), tup[1].encode("utf8"), tup[2], tup[3], tup[4].encode("utf8"), [], ix, round(val,2)]
            cards.append(card)
            continue
        tup_ixs = set([date.encode("utf8") for date in tup_ixs])
        inter = reu_id_set.intersection(tup_ixs)
        card = [reddate.encode("utf8"), tup[1].encode("utf8"), tup[2], tup[3], tup[4].encode("utf8"), inter, ix, round(val,2)]
        reu_id_set -= set(tup_ixs)
        cards.append(card)
    gc.collect()
    #Iterate over reuter ixs not covered through reddit (i.e. small cards)
    for reu_id in reu_id_set:
        date = str(reu_id)[:8]
        card = [date, reu_id, reu_id, round(reu_id_dict[reu_id], 2)]
        cards.append(card)
    id_ind= pandas.Index(id_to_reu["id"])
    head_ind= pandas.Index(id_to_reu["headline"])
    print >> sys.stderr, "populating cards with headlines"
    for each_card in cards:
        if len(each_card) == 4:
            loc= id_ind.get_loc(each_card[1])
            each_card[1]= head_ind[loc].encode("utf8")
        else:
            list_headlines=[]
            for each_id in each_card[5]:
                loc= id_ind.get_loc(each_id)
                list_headlines.append(head_ind[loc].encode("utf8"))
            each_card[5]= list_headlines
    cards.sort(key=lambda x: x[-1], reverse=True)
    gc.collect()
    return cards

if __name__ == '__main__':
    q = 'russia election hacking'
    docs = complete_search(q)
    for doc in docs:
        print(doc)
