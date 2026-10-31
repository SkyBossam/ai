import torch
from partial_labels import KnownClassBCE,known_classes

def main():
    criterion=KnownClassBCE()
    criterion.known_mask=torch.tensor([[1,1,1,1,1,0,1],[0,0,0,0,0,1,0]],dtype=torch.float32)
    logits=torch.zeros((2,3,7),requires_grad=True)
    target=torch.zeros_like(logits)
    target[0,0,6]=1
    target[1,0,5]=1
    criterion(logits,target).sum().backward()
    assert logits.grad[0,:,5].abs().sum()==0
    assert logits.grad[1,:,[0,1,2,3,4,6]].abs().sum()==0
    assert logits.grad[0,:,6].abs().sum()>0
    assert logits.grad[1,:,5].abs().sum()>0
    assert known_classes('/any/bp_train__image.jpg')==(0,1,2,3,4,6)
    assert known_classes('/any/oi_train__image.jpg')==(5,)
    try:
        known_classes('unknown.jpg')
    except ValueError:
        pass
    else:
        raise AssertionError('Unknown annotation source was accepted')
    print('PASS: unannotated classes receive zero classification gradient; known classes train normally.')

if __name__=='__main__':
    main()
