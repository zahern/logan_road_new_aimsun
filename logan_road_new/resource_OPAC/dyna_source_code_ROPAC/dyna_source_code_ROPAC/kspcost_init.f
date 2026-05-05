	subroutine kspcost_init
c --
c -- This subroutine is to initialize the arrays used in the shortest path calculations.
c --
c -- This subroutine is called from ksp_main.
c -- This subroutine does not call any other subroutines.
c --
	use muc_mod
c --
	INFINITY=3000000
	NIL=0
	MaxIm=MaxMove
	Label(:,:,:,:)=Infinity
	LabelCost(:,:,:,:)=Infinity
	Pathpointer(:,:,:,:,:)=NIL
	Pathpointer(:,:,:,:,:)=NIL
	Pathpointer(:,:,:,:,:)=NIL
	DequeLabel1(:,:,:,:)=0
	DequeLabel1Cost(:,:,:,:)=0
	DequeLabel2(:,:,:,:)=0
	FirstLabel(:,:,:)=NIL
	FirstGoodLabel(:,:,:)=NIL
	DequeLabelCounter(:,:,:)=NIL
	StatusInDeque(:)=0
c --
      Do 2002,IM=1,MaxIM
      Do 2001,Itime=1,Iti_nu
c --
c -- locat the destion node position
c -- and add the penalties to the destination nodes only
c -- a bug from Thanasis
c --
        immindex=0
        do imm=1,noof_master_destinations
          if(destin.eq.destination(imm)) immindex=imm
        enddo
        if(immindex.ne.0)then
          lod1=labelforods(ltype,ioccup,immindex,im,1)
          lod2=labelforods(ltype,ioccup,immindex,im,2)
             if(lod1.ne.0)then
                Label(Destin,Itime,1,IM)=0
c	if(Destin.gt.206.or.Destin.lt.1.or.Itime.gt.1.or.IM.gt.12)
c     +  stop
		LabelCost(Destin,Itime,1,IM)=0
             else
                Label(Destin,Itime,1,IM)=0
c	if(Destin.gt.206.or.Destin.lt.1.or.Itime.gt.1.or.IM.gt.12)
c     +  stop
	        LabelCost(Destin,Itime,1,IM)=0
             endif
        else
        Label(Destin,Itime,1,IM)=0
c	if(Destin.gt.206.or.Destin.lt.1.or.Itime.gt.1.or.IM.gt.12)
c     +  stop
	LabelCost(Destin,Itime,1,IM)=0
        endif
c --
        LabelPointer(Destin,Itime,1,IM)=NIL
        PathPointer(Destin,Itime,1,1,IM)=NIL
        PathPointer(Destin,Itime,1,2,IM)=NIL
        PathPointer(Destin,Itime,1,3,IM)=NIL
C	if(Destin.gt.206.or.itime.gt.1.or.im.gt.12) stop
        DequeLabel1(Destin,Itime,1,IM)=0
        DequeLabel1Cost(Destin,Itime,1,IM)=0
	DequeLabel2(Destin,Itime,1,IM)=1
        DequeLabelCounter(Destin,Itime,IM)=1
        FirstGoodLabel(Destin,Itime,IM)=1
        FirstLabel(Destin,Itime,IM)=1
2001    Continue
2002	Continue
	FirstDeque=Destin
	LastDeque=Destin
	StatusInDeque(Destin)=INFINITY
c        Do 1, Mov=1,nu_mv
         Do 1,Mov=1,MaxMove
         Do 1,K=1,KPaths+1
          Do 1,Itime=1,Iti_nu
1           Update(Mov,Itime,K)=.FALSE.
c --
	Return
	End
