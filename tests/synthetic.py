"""Nonconfidential assessment fixtures; no reference-set data."""
from copy import deepcopy
TEXT = [
 'Welcome to our practice lesson. Today we will compare equal fractions using a number line and explain each answer together.',
 'What does the denominator tell us? Take a moment to explain your reasoning. You can draw equal parts to support your answer.',
 'I think it counts all the equal pieces in one whole. Yes, that is right. Now compare one half with one quarter using identical wholes.',
 'One quarter looks bigger because four is bigger than two. Thank you for explaining. With more equal pieces, each piece is smaller. Can you revise your answer?',
 'I see that one half is bigger when the whole is the same. That is a clear explanation. Could another learner show a different example?',
 'To recap, compare the same whole and use equal parts. Try two examples after class. What questions remain about the number line?',
]


def payload():
    return {'reviewed':True,'deidentified':True,'speakers_reliable':False,
            'coverage':{'kind':'complete','duration_seconds':120},
            'segments':[{'id':f'S{i+1:04d}','start':i*20,'end':(i+1)*20,'text':t,'speaker':None} for i,t in enumerate(TEXT)]}


def result():
    from assessment import DIMENSIONS
    return deepcopy({'status':'assessed','summary':'Synthetic fixture assessment; not a real class evaluation.',
      'evidence':[{'id':f'E{i+1:02d}','segment_ids':[f'S{i+1:04d}'],'start':i*20,'end':(i+1)*20,
                   'quote':t.split('.')[0]+'.' if '.' in t else t,'observation':'An explanation or response appears in this segment.',
                   'interpretation':'This may support learning, subject to transcript accuracy.'} for i,t in enumerate(TEXT[:4])],
      'dimensions':[{'name':name,'status':'observed','score':2,'evidence_ids':[f'E{i+1:02d}'],'assessment':'Useful practice is evidenced in the cited segment.'} for i,name in enumerate(DIMENSIONS)],
      'strengths':[{'evidence_ids':['E01'],'detail':'The objective is introduced.'}],
      'improvements':[{'evidence_ids':['E02'],'action':'Ask a follow-up that requires the learner to explain a new example.'}],
      'limitations':['Synthetic fixture only; not quality evaluation.']})
