def main():
    dataset_name_lsit = ['brown_bm_3_05',
                        'cogsci2_05',
                        'cogsci6_05',
                        'cogsci8_05',
                        'cs3_05',
                        'cs7_05',
                        'buckingham',
                        'fountain',
                        'gms-large-cabinet',
                        'gms-teddy',
                        'hv_c4_1_05',
                        'hv_c10_2_05',
                        'harvard_conf_big_05_fix',
                        'hv_lounge1_2_05',
                        'hv_s1_2_05',
                        'herzjesu',
                        'home_ac_05_fix',
                        'florence_hotel_05',
                        'mit_32_g725_05',
                        'mit_46_6conf_05',
                        'mit_46_6lounge_05',
                        'mit_w85g_05',
                        'mit_w85h_05',
                        'notre_dame',
                        'reichstag',
                        'sacre_coeur',
                        'st_peters',]
    base_str = './dump_data.py --data_tr={0} --data_va={0} --data_te={0} --precomputed_kp_method="lfnet"'
    for dataset_name in dataset_name_lsit:
        command = base_str.format(dataset_name)
        with open('./jobs/todo/{0}.sh'.format(dataset_name), 'w') as f:
            f.write("#!/bin/bash\n")
            f.write("source ~/.bashrc\n")
            f.write("conda activate torch1.0\n")
            f.write('{0}\n'.format(command))

if __name__ == '__main__':
    main()
