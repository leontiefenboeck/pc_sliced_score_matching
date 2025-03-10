import os
import torch
from tqdm import tqdm
import numpy as np

from EinsumNetwork import Graph, EinsumNetwork
import utils

device = 'cuda' if torch.cuda.is_available() else 'cpu'

algorithms = ['SSM', 'SGD', 'EM']
algorithms = ['SSM']

dataset = 'mnist'       # choose either mnist or fashion-mnist

# ------------------------ constants -------------------------------
exponential_family = EinsumNetwork.BinomialArray
exponential_family_args = {'N': 255}

classes = [7] # in which mnist class to train on

n_slices = 1 # number of slices for SSM

num_epochs = 20
lr = 0.2
lr_decay = 0.5
lr_decay_step = 5
clip_grad = True

batch_size = 100

K = 10
pd_num_pieces = [4]
width = 28
height = 28

online_em_frequency = 1
online_em_stepsize = 0.05

# ------------------------ training -------------------------------
train_x, valid_x, test_x = utils.get_data(dataset, classes, exponential_family, device)

train_N = train_x.shape[0]
valid_N = valid_x.shape[0]
test_N = test_x.shape[0]

pd_delta = [[height / d, width / d] for d in pd_num_pieces]
graph = Graph.poon_domingos_structure(shape=(height, width), delta=pd_delta)

print(f" \n Training on {dataset} with classes {classes} \n")

for a in algorithms:
    use_em = False

    if a == 'EM': 
        use_em = True 

    args = EinsumNetwork.Args(
            num_var=train_x.shape[1],
            num_dims=1,
            num_classes=1,
            num_sums=K,
            num_input_distributions=K,
            exponential_family=exponential_family,
            exponential_family_args=exponential_family_args,
            use_em=use_em,
            online_em_frequency=online_em_frequency,
            online_em_stepsize=online_em_stepsize)

    einet = EinsumNetwork.EinsumNetwork(graph, args)
    einet.initialize()
    einet.to(device)

    optimizer = torch.optim.Adam(einet.parameters(), lr=lr)
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, lr_decay_step, lr_decay)

    train_losses, val_losses = [], []

    pbar = tqdm(range(num_epochs), desc=f"[{a}] -- logp {0:.2f}", ncols=100)
    for epoch_count in pbar:

        einet.eval()
        valid_ll = EinsumNetwork.eval_loglikelihood_batched(einet, valid_x, batch_size=batch_size) / valid_N
        train_ll = EinsumNetwork.eval_loglikelihood_batched(einet, train_x, batch_size=batch_size) / train_N
        train_losses.append(-train_ll)
        val_losses.append(-valid_ll)
        pbar.set_description(f"[{a}] logp: {train_ll:.2f}")
        einet.train()

        idx_batches = torch.randperm(train_N, device=device).split(batch_size)

        for i, idx in enumerate(idx_batches):
            batch_x = train_x[idx, :]

            if a == 'EM':
                logp = EinsumNetwork.log_likelihoods(einet.forward(batch_x))
                logp = logp.sum()
                logp.backward()
                einet.em_process_batch()
            else:             
                if a == 'SSM':
                    loss = utils.ssm_loss(einet, batch_x, n_slices)
                if a == 'SGD':
                    loss = -torch.mean(EinsumNetwork.log_likelihoods(einet.forward(batch_x)))

                optimizer.zero_grad()
                loss.backward()
                if clip_grad: torch.nn.utils.clip_grad_norm_(einet.parameters(), 1.0)
                optimizer.step()

        if a != 'EM': scheduler.step()
        else : einet.em_update()

    # ------------- evaluate ---------------
    einet.eval()

    save_dir = 'results/'
    utils.mkdir_p(save_dir)  

    # print final losses
    train_ll = EinsumNetwork.eval_loglikelihood_batched(einet, train_x, batch_size=batch_size) / train_N
    valid_ll = EinsumNetwork.eval_loglikelihood_batched(einet, valid_x, batch_size=batch_size) / valid_N
    test_ll = EinsumNetwork.eval_loglikelihood_batched(einet, test_x, batch_size=batch_size) / test_N
    train_losses.append(-train_ll)
    val_losses.append(-valid_ll)
    print(f"EVAL:   train LL {train_ll:.02f}   valid LL {valid_ll:.02f}   test LL {test_ll:.02f} \n")

    # plot train and val losses
    # utils.plot_losses(train_losses, val_losses, os.path.join(save_dir, f"{dataset}{classes}_{a}_losses.png"))
    
    # sampling
    samples = einet.sample(num_samples=25).cpu().numpy()
    samples = samples.reshape((-1, 28, 28))
    utils.save_image_stack(samples, 5, 5, os.path.join(save_dir, f"{dataset}{classes}_{a}_samples_{num_epochs}_{lr}.png"), margin_gray_val=0.)

    # reconstruction 
    image_scope = np.array(range(height * width)).reshape(height, width)
    marginalize_idx = list(image_scope[0:round(height/2), :].reshape(-1))
    keep_idx = [i for i in range(width*height) if i not in marginalize_idx]
    einet.set_marginalization_idx(marginalize_idx)

    masked_images = test_x[0:25, :].clone().cpu().numpy()
    masked_images[:, marginalize_idx] = 0 
    masked_images = masked_images.reshape((-1, 28, 28))
    # utils.save_image_stack(masked_images, 5, 5, os.path.join(save_dir, f"{dataset}{classes}_{a}_masked_images_{num_epochs}_{lr}.png"), margin_gray_val=0.)

    num_samples = 10
    samples = None
    for k in range(num_samples):
        if samples is None:
            samples = einet.sample(x=test_x[0:25, :]).cpu().numpy()
        else:
            samples += einet.sample(x=test_x[0:25, :]).cpu().numpy()
    samples /= num_samples
    samples = samples.squeeze()

    samples = samples.reshape((-1, 28, 28))
    # utils.save_image_stack(samples, 5, 5, os.path.join(save_dir, f"{dataset}{classes}_{a}_sample_reconstruction_{num_epochs}_{lr}.png"), margin_gray_val=0.)

# ground truth
ground_truth = test_x[0:25, :].cpu().numpy()
ground_truth = ground_truth.reshape((-1, 28, 28))
utils.save_image_stack(ground_truth, 5, 5, os.path.join(save_dir, f'{dataset}{classes}_ground_truth.png'), margin_gray_val=0.)
