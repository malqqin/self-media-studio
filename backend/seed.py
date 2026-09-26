from . import db

SOURCES = {
 'webb': {
  'id':'webb-colors', 'title':'How Are Webb’s Full-Color Images Made?', 'publisher':'STScI / Webb',
  'url':'https://webbtelescope.org/contents/articles/how-are-webbs-full-color-images-made',
  'text':'Webb’s raw telescope images initially appear almost completely black. They are initially transformed by image processors into crisp black-and-white images and then full-color composites. Webb’s infrared light is mapped to the visible light our eyes can perceive. The search results detail which filters Webb used to observe the target. Image specialists stretch Webb’s images to see variation in the pixel values and highlight what was captured.'},
 'orbit': {
  'id':'nasa-gravity', 'title':'Chapter 3: Gravity & Mechanics', 'publisher':'NASA',
  'url':'https://science.nasa.gov/learn/basics-of-space-flight/chapter3-2/',
  'text':'Sir Isaac Newton realized that the force that makes apples fall to the ground is the same force that makes the planets "fall" around the Sun. Circular orbits are merely a special case of an ellipse where the foci are coincident. Every body continues in a state of rest, or of uniform motion in a straight line, unless it is compelled to change that state by forces impressed upon it. If the acceleration is produced by a force at some other angle to the velocity, the object will be deflected.'},
 'particle': {
  'id':'cern-accelerators', 'title':'Accelerators', 'publisher':'CERN',
  'url':'https://home.cern/science/accelerators/',
  'text':'An accelerator propels charged particles, such as protons or electrons, at high speeds, close to the speed of light. Accelerators use electromagnetic fields to accelerate and steer particles. Radiofrequency cavities boost the particle beams, while magnets focus the beams and bend their trajectory. In a circular accelerator, the particles repeat the same circuit for as long as necessary, getting an energy boost at each turn. By studying these collisions, physicists are able to probe the world of the infinitely small.'}
}

SAMPLES = [
 {'id':'sample-webb','title':'韦布拍到的颜色，是太空本来的颜色吗？','category':'astronomy','source':'STScI / Webb','key':'webb',
  'angle':'从熟悉的宇宙照片切入，解释观测波段如何变成可见颜色。',
  'scenes':[
   ('照片里的颜色','看到绚丽的宇宙照片，你有没有想过：如果我们真的站在那里，看到的也会是这些颜色吗？要回答这个问题，先要知道，望远镜记录的数据，是怎样变成照片的。','Webb’s raw telescope images initially appear almost completely black.'),
   ('先有数据，再有图像','韦布传回的原始图像，并不是我们最后看到的彩色成片。工作人员先处理不同观测获得的图像，再把它们组合起来。最终的画面，是对观测信息的一种呈现。','They are initially transformed by image processors into crisp black-and-white images and then full-color composites.'),
   ('让不可见，变得可见','韦布观测的红外光，超出了人眼可见的范围。为了让我们看见其中的信息，图像处理人员把红外观测映射成可见颜色。这是对数据的表达，不是把普通照片随意染色。','Webb’s infrared light is mapped to the visible light our eyes can perceive.'),
   ('每个波段，都有信息','不同滤镜记录不同的观测信息。处理人员还会调整图像的显示范围，让原本很暗的细节显现出来。理解这张照片，需要同时看它采用的滤镜与处理说明。','Image specialists stretch Webb’s images to see variation in the pixel values and highlight what was captured.'),
   ('看美，也读懂科学','所以，欣赏宇宙照片时，我们可以多问一句：这些颜色分别表达什么？它们帮助我们理解真实的观测，却不一定等于肉眼站在现场看到的样子。','Webb’s infrared light is mapped to the visible light our eyes can perceive.') ]},
 {'id':'sample-orbit','title':'卫星一直在下落，为什么没有掉到地上？','category':'spaceflight','source':'NASA','key':'orbit',
  'angle':'用“下落却不落地”的直觉冲突，解释轨道运动。',
  'scenes':[
   ('为什么没掉下来？','卫星绕着地球飞行，看起来好像摆脱了引力。但理解轨道，恰恰需要引力。让苹果落地的吸引作用，也和天体为什么绕行有关。','Sir Isaac Newton realized that the force that makes apples fall to the ground is the same force that makes the planets "fall" around the Sun.'),
   ('先想象一条直线','如果没有外力改变运动状态，一个物体会保持静止，或者沿直线匀速运动。所以，一个物体不断转弯，就说明它的运动状态一直在改变。','Every body continues in a state of rest, or of uniform motion in a straight line, unless it is compelled to change that state by forces impressed upon it.'),
   ('引力，让路径弯曲','卫星一边向前运动，一边受到地球引力，运动方向不断改变。在适当的初始条件下，它的路径绕过地球，形成轨道。示意图里的距离和大小，并不按实际比例绘制。','If the acceleration is produced by a force at some other angle to the velocity, the object will be deflected.'),
   ('圆，只是一个特例','我们常把轨道画成圆，是为了容易理解。实际上，圆形轨道只是椭圆轨道的一种特殊情况。理解轨道时，需要一起考虑速度的方向，以及引力的作用。','Circular orbits are merely a special case of an ellipse where the foci are coincident.'),
   ('一直下落，一直向前','所以，绕行并不意味着没有引力。卫星同时在向前运动和改变方向。下一次看到地球旁的轨道线，可以把它想成一条不断被引力弯曲的路径。','If the acceleration is produced by a force at some other angle to the velocity, the object will be deflected.') ]},
 {'id':'sample-particle','title':'粒子加速器，究竟在加速什么？','category':'physics','source':'CERN','key':'particle',
  'angle':'区分提供能量与引导轨迹，走近大型科学装置。',
  'scenes':[
   ('大机器，小粒子','看到巨大的粒子加速器，你可能会问：这么大的机器，到底在加速什么？答案是带电粒子，例如质子或电子。它们可以被加速到非常高的速度。','An accelerator propels charged particles, such as protons or electrons, at high speeds, close to the speed of light.'),
   ('是谁提供能量？','加速器利用电磁场来加速和引导粒子。在许多装置中，射频腔为粒子束补充能量。想理解它，可以先把提供能量和引导方向，分成两件事来看。','Accelerators use electromagnetic fields to accelerate and steer particles.'),
   ('磁铁，引导方向','射频腔给粒子束增加能量，而磁铁帮助聚焦粒子束，并弯曲它们的路径。图中的轨迹只是原理示意，不代表真实装置的尺寸和全部结构。','Radiofrequency cavities boost the particle beams, while magnets focus the beams and bend their trajectory.'),
   ('一圈，再一圈','在环形加速器里，粒子可以一次次经过同一条回路，每一圈获得进一步的能量。很大的科学装置，就是这样控制着非常微小的粒子束。','In a circular accelerator, the particles repeat the same circuit for as long as necessary, getting an energy boost at each turn.'),
   ('从碰撞里寻找答案','研究人员让高能粒子发生碰撞，分析碰撞产生的结果，从而研究微观世界。加速器的意义，就在于帮助我们把看不见的结构，变成可以测量的线索。','By studying these collisions, physicists are able to probe the world of the infinitely small.') ]}
]


def init():
    with db.connect() as c:
        for i, sample in enumerate(SAMPLES):
            source = SOURCES[sample['key']]
            selected=[sample['scenes'][0],sample['scenes'][2]]
            if sample['key']=='webb':selected=[sample['scenes'][2],sample['scenes'][2]]
            scenes=[{'heading':h,'source_id':source['id'],'evidence':e,
                     'visual':'spectrum' if sample['key']=='webb' else sample['key'],'asset_id':'','clip_start':0}
                    for h,n,e in selected]
            titles={'webb':['韦布眼中的宇宙','把红外光，变成看得见的色彩'],
                    'orbit':['卫星一直在下落','引力让它的路径不断弯曲'],
                    'particle':['粒子加速器，在加速什么？','质子、电子等带电粒子']}
            media=[]
            if sample['key']=='webb':
                scenes[0]['heading']='船底座星云 · 宇宙悬崖'
                scenes[1]['heading']='南环星云 · 两种红外视角'
                for ident,filename in [('carina_nebula','宇宙悬崖'),('southern_ring_nebula','南环星云')]:
                    media.append({'url':f'https://images-assets.nasa.gov/image/{ident}/{ident}~medium.jpg',
                        'page_url':f'https://images.nasa.gov/details/{ident}','filename':filename,
                        'credit':'NASA / ESA / CSA / STScI',
                        'rights':'NASA Image and Video Library 官方科学图像；保留署名，发布前核对原始使用条件'})
            data={'angle':sample['angle'],'sources':[source], 'media':media,
                  'rights':'NASA 官方韦布图片 · 保留署名并人工核验' if media else '原创科学示意，可替换成相关图片或视频',
                  'evidence_status':'内置资料摘录 · 最终需人工核验',
                  'seed_script':{'title':sample['title'],'description':sample['angle'],'title_lines':titles[sample['key']],'scenes':scenes}}
            c.execute('INSERT INTO topics(id,title,category,kind,source,published_at,discovered_at,score,data) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(owner_id,id) DO UPDATE SET data=excluded.data',
                      (sample['id'],sample['title'],sample['category'],'sample',sample['source'],None,db.now(),90-i,db.dump(data)))
